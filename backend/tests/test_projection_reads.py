"""Real commits between projection reads must not mix old and new facts."""

import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlmodel import Session

from app.core.db import engine
from app.model_config.service import lock_owner
from app.training import submissions
from app.training.evaluation_models import Evaluation
from app.training.independent_models import IndependentObservation
from app.training.models import TrainingRun
from tests.test_accounts import client
from tests.test_evaluations import start as start_evaluation
from tests.test_independent_api import checked as checked
from tests.test_independent_api import frozen as frozen
from tests.test_independent_api import origin as origin
from tests.test_independent_api import provider as provider


def held_get(auth, url, release):
    # The provider (or the explicit topic gate below) still holds User FOR UPDATE.
    # A public poll must finish before that gate is released, not wait for network.
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.get, url, headers=auth)
        try:
            response = future.result(timeout=2)
            assert response.status_code == 200, response.text
            return response.json()
        except BaseException:
            release()
            raise


def wait_persisted(predicate):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with Session(engine) as s:
            if predicate(s):
                return
        time.sleep(0.01)
    raise AssertionError("writer did not commit")


def submit(auth, run_id, config):
    r = client.post(
        f"/api/v1/training/tasks/{run_id}/submissions",
        headers=auth,
        json={
            "request_id": str(uuid.uuid4()),
            "expected_config_version": config["version"],
            "disclosure_accepted": True,
            "answers": [
                {
                    "judgment_id": "j1",
                    "value": 0,
                    "reason": "提交成功已确认，应保留已有结果，避免重新执行。",
                }
            ],
        },
    )
    assert r.status_code == 202


def test_submission_snapshot(checked, provider, monkeypatch):
    auth, run_id, config = checked
    provider["mode"] = "hold"
    provider["received"].clear()
    submit(auth, run_id, config)
    assert provider["received"].wait(10)
    pending = held_get(
        auth, f"/api/v1/training/tasks/{run_id}/submissions", provider["release"].set
    )
    assert pending["submissions"][-1]["status"] == "checking"
    assert pending["completed_at"] is None and pending["awarded_points"] == 0
    original = submissions.owned

    def barrier(s, identity, owner):
        run = original(s, identity, owner)
        assert run.formal_submitted_at is None
        provider["release"].set()
        wait_persisted(
            lambda db: (
                db.get(TrainingRun, uuid.UUID(run_id)).formal_submitted_at is not None
            )
        )
        return run

    monkeypatch.setattr(submissions, "owned", barrier)
    state = client.get(
        f"/api/v1/training/tasks/{run_id}/submissions", headers=auth
    ).json()
    completed = state["submissions"][-1]["status"] == "completed"
    assert (state["completed_at"] is not None) == completed
    assert state["awarded_points"] == (10 if completed else 0)
    monkeypatch.setattr(submissions, "owned", original)
    latest = client.get(
        f"/api/v1/training/tasks/{run_id}/submissions", headers=auth
    ).json()
    assert latest["submissions"][-1]["status"] == "completed"
    assert latest["completed_at"] is not None and latest["awarded_points"] == 10


def test_evaluation_snapshot(checked, provider, monkeypatch):
    auth, run_id, config = checked
    submit(auth, run_id, config)
    wait_persisted(
        lambda db: (
            db.get(TrainingRun, uuid.UUID(run_id)).formal_submitted_at is not None
        )
    )
    provider["mode"] = "hold"
    provider["received"].clear()
    start_evaluation(auth, run_id, config)
    assert provider["received"].wait(10)
    pending = held_get(
        auth, f"/api/v1/training/tasks/{run_id}/evaluation", provider["release"].set
    )
    assert pending["status"] == "checking" and pending["independent_outcome"] is None
    original = Session.exec
    fired = False

    def intercept(s, q, *args, **kwargs):
        nonlocal fired
        result = original(s, q, *args, **kwargs)
        descriptions = getattr(q, "column_descriptions", [])
        if (
            not fired
            and descriptions
            and descriptions[0].get("entity") is IndependentObservation
        ):
            fired = True
            value = result.first()
            assert value is None
            provider["release"].set()
            wait_persisted(
                lambda db: db.get(Evaluation, uuid.UUID(run_id)).status == "completed"
            )

            class Result:
                def first(self):
                    return value

            return Result()
        return result

    monkeypatch.setattr(Session, "exec", intercept)
    state = client.get(
        f"/api/v1/training/tasks/{run_id}/evaluation", headers=auth
    ).json()
    assert fired
    assert (state["status"] == "completed") == (
        state["independent_outcome"] is not None
    )
    latest = client.get(
        f"/api/v1/training/tasks/{run_id}/evaluation", headers=auth
    ).json()
    assert latest["status"] == "completed"
    assert latest["independent_outcome"] == "independent_pass_candidate"


@pytest.mark.parametrize("listed", [False, True])
def test_topic_snapshot(provider, monkeypatch, listed):
    import json

    from app.training.topic_models import Topic, TopicJob, TopicVersion
    from app.training.topic_worker import accept
    from tests.test_model_config import account, save
    from tests.test_topics import interpretation

    owner, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    with Session(engine) as db:
        topic = Topic(user_id=owner)
        db.add(topic)
        db.flush()
        job = TopicJob(
            id=uuid.uuid4(),
            user_id=owner,
            topic_id=topic.id,
            input_text="判断确认丢失时的重试",
            config_version=uuid.UUID(config["version"]),
            destination=provider["url"],
            model_id=config["model_id"],
            stage="inspect",
            candidate=interpretation(),
            status="running",
        )
        db.add(job)
        db.commit()
        topic_id, job_id = topic.id, job.id
    url = "/api/v1/topics" if listed else f"/api/v1/topics/{topic_id}"
    with Session(engine) as gate:
        lock_owner(gate, owner)
        held_get(auth, url, gate.rollback)
    original = Session.exec
    fired = False

    def intercept(s, q, *args, **kwargs):
        nonlocal fired
        result = original(s, q, *args, **kwargs)
        descriptions = getattr(q, "column_descriptions", [])
        if not fired and descriptions and descriptions[0].get("entity") is TopicVersion:
            fired = True
            assert accept(
                job_id,
                json.dumps(
                    {"accepted": True, "explanation": "实际目标、重点与案例一致"}
                ),
                None,
            )
        return result

    monkeypatch.setattr(Session, "exec", intercept)
    result = client.get(url, headers=auth).json()
    state = (
        next(row for row in result if row["id"] == str(topic_id)) if listed else result
    )
    assert fired
    completed = state["jobs"][0]["status"] == "completed"
    assert (state["current"] is not None) == completed
    assert len(state["versions"]) == int(completed)
    latest = client.get(f"/api/v1/topics/{topic_id}", headers=auth).json()
    assert latest["jobs"][0]["status"] == "completed"
    assert latest["current"]["id"] == latest["versions"][0]["id"]
