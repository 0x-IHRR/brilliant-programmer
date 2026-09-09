import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from sqlalchemy import text
from sqlmodel import Session, select

from app.core.db import engine
from app.training.models import TrainingRun
from app.training.submission_models import PracticeAward, Submission
from tests.draft_requests import put, snapshot
from tests.test_accounts import client
from tests.test_model_config import account
from tests.test_submissions import (  # noqa: F401
    payload,
    wait_submission,
)
from tests.test_submissions import (
    provider as submission_provider,
)
from tests.test_submissions import (
    ready as submission_ready,
)
from tests.test_submissions import url as submission_url

provider = submission_provider
ready = submission_ready


def url(run_id):
    return f"/api/v1/training/tasks/{run_id}/draft"


def draft(version=None, base=None, **progress):
    return {
        "request_id": str(uuid.uuid4()),
        "expected_version": version,
        "progress": {
            "answers": [],
            "step": "judgments",
            "based_on_submission_id": base,
            **progress,
        },
    }


def test_draft_partial_replay_owner_and_no_business_facts(ready, provider):
    owner, auth, run_id, *_ = ready
    assert client.get(url(run_id), headers=auth).json() is None
    body = draft(answers=[{"judgment_id": "j2", "value": [-1, 1], "reason": ""}])
    result = put(url(run_id), headers=auth, json=body)
    assert result.status_code == 200, result.text
    assert result.headers["cache-control"] == "no-store"
    saved = result.json()
    assert saved["progress"] == body["progress"]
    assert put(url(run_id), headers=auth, json=body).json() == saved
    assert client.get(url(run_id), headers=auth).json() == snapshot(saved)
    assert put(url(run_id), headers=auth, json=draft()).status_code == 409
    changed = {**body, "progress": {**body["progress"], "step": "coach"}}
    assert put(url(run_id), headers=auth, json=changed).status_code == 409
    _, other = account()
    assert client.get(url(run_id), headers=other).status_code == 404
    assert put(url(run_id), headers=other, json=body).status_code == 404
    assert client.get(url(run_id)).status_code == 401
    with Session(engine) as session:
        run = session.get(TrainingRun, uuid.UUID(run_id))
        assert run.formal_submitted_at is None
        assert run.event_sequence == 0
        assert not session.exec(
            select(Submission).where(Submission.run_id == run.id)
        ).all()
        assert not session.exec(
            select(PracticeAward).where(PracticeAward.user_id == owner)
        ).all()
    assert len(provider["requests"]) == 1


def test_concurrent_same_version_has_one_winner(ready):
    _, auth, run_id, *_ = ready
    first = put(url(run_id), headers=auth, json=draft()).json()
    barrier = Barrier(2)

    def save(step):
        barrier.wait(timeout=5)
        return put(url(run_id), headers=auth, json=draft(first["version"], step=step))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ["materials", "coach"]))
    assert sorted(r.status_code for r in results) == [200, 409]
    winner = next(r.json() for r in results if r.status_code == 200)
    assert client.get(url(run_id), headers=auth).json() == snapshot(winner)


def test_formal_lineage_blocks_old_editor_without_overwriting_original(ready):
    _, auth, run_id, config, _, control = ready
    options = json.loads(control.read_text())
    control.write_text(json.dumps({**options, "before_submission_ok": True}))
    saved = put(url(run_id), headers=auth, json=draft()).json()
    original = payload(config)
    assert (
        client.post(submission_url(run_id), headers=auth, json=original).status_code
        == 202
    )
    deadline = time.monotonic() + 5
    while not control.with_name(control.name + ".submission_ok_pending").exists():
        assert time.monotonic() < deadline, "worker did not reach final attempt write"
        time.sleep(0.02)
    state = wait_submission(auth, run_id)
    assert state["awarded_points"] == 10
    assert state["submissions"][0]["attempts"][0]["code"] == "unknown"
    control.write_text(json.dumps(options))
    deadline = time.monotonic() + 5
    final = state
    while final["submissions"][0]["attempts"][0]["code"] == "unknown":
        assert time.monotonic() < deadline, "final attempt outcome was not persisted"
        final = wait_submission(auth, run_id)
        time.sleep(0.02)
    assert final["submissions"][0]["attempts"][0]["code"] == "ok"
    # Compare only after both the immutable result and its attempt outcome commit.
    state = final
    assert state["awarded_points"] == 10
    assert (
        put(url(run_id), headers=auth, json=draft(saved["version"])).status_code == 409
    )
    assert client.get(url(run_id), headers=auth).json() == snapshot(saved)
    assert (
        client.delete(
            "/api/v1/model-config",
            headers=auth,
            params={"expected_version": config["version"]},
        ).status_code
        == 204
    )
    update = draft(
        saved["version"],
        original["request_id"],
        answers=[{"judgment_id": "j1", "value": None, "reason": "继续想"}],
    )
    response = put(url(run_id), headers=auth, json=update)
    assert response.status_code == 200, response.text
    after = client.get(submission_url(run_id), headers=auth).json()
    assert after == state
    assert after["submissions"][0]["answers"] == original["answers"]
    collection = client.get(url(run_id) + "/versions", headers=auth).json()
    selected = client.post(
        url(run_id) + "/choose",
        headers=auth,
        json={"observed_revision": collection["revision"], "version": saved["version"]},
    )
    assert selected.status_code == 200
    removed = client.request(
        "DELETE",
        url(run_id),
        headers=auth,
        json={
            "observed_revision": selected.json()["revision"],
            "version": saved["version"],
        },
    )
    assert removed.status_code == 200
    assert client.get(url(run_id), headers=auth).json() is None
    assert client.get(submission_url(run_id), headers=auth).json() == state


@pytest.mark.parametrize("draft_first", [True, False])
def test_save_and_submit_have_one_lineage_order(ready, monkeypatch, draft_first):
    from app.training import drafts, submissions

    _, auth, run_id, config, *_ = ready
    observed = client.get(url(run_id) + "/versions", headers=auth).json()
    save_body = {
        **draft(),
        "observed_revision": observed["revision"],
        "generation": observed["generation"],
    }
    entered, release = Event(), Event()
    leader = drafts if draft_first else submissions
    original_lock = leader.lock_owner

    def held_lock(session, owner):
        result = original_lock(session, owner)
        entered.set()
        assert release.wait(10)
        return result

    monkeypatch.setattr(leader, "lock_owner", held_lock)
    original = payload(config)

    def save():
        return client.put(url(run_id), headers=auth, json=save_body)

    def submit():
        return client.post(submission_url(run_id), headers=auth, json=original)

    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(save if draft_first else submit)
        try:
            assert entered.wait(5)
            second = pool.submit(submit if draft_first else save)
            deadline = time.monotonic() + 5
            while True:
                with Session(engine) as session:
                    waiting = session.execute(
                        text(
                            "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND query LIKE 'SELECT \"user\".%FOR UPDATE%' "
                        )
                    ).scalar()
                if waiting:
                    break
                assert time.monotonic() < deadline, (
                    "follower did not wait on database lock"
                )
                time.sleep(0.02)
            assert not second.done()
        finally:
            release.set()
        first_response, second_response = first.result(10), second.result(10)
    saved_response = first_response if draft_first else second_response
    submitted_response = second_response if draft_first else first_response
    assert submitted_response.status_code == 202
    assert saved_response.status_code == (200 if draft_first else 409)
    saved = client.get(url(run_id), headers=auth).json()
    assert (saved is not None) is draft_first
    if saved:
        assert saved["progress"]["based_on_submission_id"] is None
    state = wait_submission(auth, run_id)
    assert state["submissions"][0]["answers"] == original["answers"]
    assert len(state["submissions"]) == 1 and state["awarded_points"] == 10
