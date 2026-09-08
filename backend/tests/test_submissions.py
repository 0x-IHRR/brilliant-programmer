import copy
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import pytest
from sqlmodel import Session, select

from app.core.db import engine
from app.models import User
from app.training.models import TrainingRun
from app.training.submission_models import PracticeAward, Submission
from app.training.submission_schema import Relevance
from app.training.submission_worker import settle
from tests.test_accounts import client
from tests.test_model_config import FAKE_KEY, account
from tests.test_training import (  # noqa: F401
    provider as training_provider,
)
from tests.test_training import (
    start_run,
    start_worker,
    stop_worker,
    wait_run,
)

provider = training_provider


@pytest.fixture
def ready(tmp_path, provider):
    provider["all_kinds"] = True
    owner, auth, run_id = start_run(provider)
    process, control = start_worker(tmp_path, provider, run_id)
    try:
        assert wait_run(auth, run_id).json()["status"] == "completed"
        config = client.get("/api/v1/model-config", headers=auth).json()
        yield owner, auth, run_id, config, process, control
    finally:
        stop_worker(process)


def payload(config, **changes):
    return {
        "request_id": str(uuid.uuid4()),
        "expected_config_version": config["version"],
        "disclosure_accepted": True,
        "answers": [
            {
                "judgment_id": "j1",
                "value": 1,
                "reason": "没收到确认，所以我觉得没有执行。",
            },
            {
                "judgment_id": "j2",
                "value": [2, 1, 0],
                "reason": "我想先检查结果，再查请求记录。",
            },
            {
                "judgment_id": "j3",
                "value": "不会执行",
                "reason": "不知道原因，需要再查看请求和确认记录。",
            },
        ],
        **changes,
    }


def url(run_id):
    return f"/api/v1/training/tasks/{run_id}/submissions"


def wait_submission(auth, run_id):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        response = client.get(url(run_id), headers=auth)
        assert response.status_code == 200, response.text
        if response.json()["submissions"][-1]["status"] not in {"checking", "stopping"}:
            return response.json()
        time.sleep(0.04)
    raise AssertionError(response.text)


def test_all_required_wrong_answers_complete_once_with_real_worker(ready, provider):
    owner, auth, run_id, config, *_ = ready
    body = payload(config)
    result = client.post(url(run_id), headers=auth, json=body)
    assert result.status_code == 202, result.text
    result = wait_submission(auth, run_id)
    assert result["awarded_points"] == result["total_points"] == 10
    assert result["completed_at"] and result["rule_version"] == "completion-v1.0"
    assert result["submissions"][0]["answers"] == body["answers"]
    assert result["submissions"][0]["status"] == "completed"
    repeat = client.post(url(run_id), headers=auth, json=body)
    assert repeat.status_code == 202 and repeat.json()["awarded_points"] == 10
    assert (
        client.post(
            url(run_id), headers=auth, json={**body, "request_id": str(uuid.uuid4())}
        ).json()["submissions"][0]["id"]
        == body["request_id"]
    )
    changed = copy.deepcopy(body)
    changed["answers"][0]["value"] = 0
    assert client.post(url(run_id), headers=auth, json=changed).status_code == 409
    assert len(provider["requests"]) == 2
    context = json.loads(provider["requests"][-1]["messages"][1]["content"])
    assert set(context) == {
        "purpose",
        "task",
        "assumptions",
        "evidence",
        "judgments",
        "answers",
        "schema",
    }
    assert (
        "HIDDEN_" not in str(context)
        and FAKE_KEY not in str(context)
        and "email" not in str(context)
    )
    assert "HIDDEN_" not in repeat.text
    assert repeat.headers["cache-control"] == "no-store"
    with Session(engine) as session:
        assert (
            len(
                session.exec(
                    select(PracticeAward).where(PracticeAward.user_id == owner)
                ).all()
            )
            == 1
        )
        user = session.get(User, owner)
        assert user.level == "小白程序员"
        original = session.get(Submission, uuid.UUID(body["request_id"]))
        original.answers = []
        with pytest.raises(Exception, match="immutable submission input"):
            session.commit()
        session.rollback()
        run = session.get(TrainingRun, uuid.UUID(run_id))
        run.formal_submitted_at = datetime.now(UTC)
        with pytest.raises(Exception, match="immutable formal submission time"):
            session.commit()


def test_missing_invalid_unowned_and_secret_inputs_never_complete(ready, provider):
    _, auth, run_id, config, *_ = ready
    body = payload(config)
    bad = []
    for value in [None, True, "1", 9]:
        changed = copy.deepcopy(body)
        changed["answers"][0]["value"] = value
        bad.append(changed)
    for order in [[0, 0, 1], [0, 1], [0, True, 2]]:
        changed = copy.deepcopy(body)
        changed["answers"][1]["value"] = order
        bad.append(changed)
    for value in ["", "   ", 0]:
        changed = copy.deepcopy(body)
        changed["answers"][2]["value"] = value
        bad.append(changed)
    for reason in ["", "   ", FAKE_KEY, "sk-" + "A" * 26]:
        changed = copy.deepcopy(body)
        changed["answers"][0]["reason"] = reason
        bad.append(changed)
    bad += [
        {**body, "answers": body["answers"][:2]},
        {**body, "user_id": str(uuid.uuid4())},
        {**body, "disclosure_accepted": False},
    ]
    for changed in bad:
        response = client.post(url(run_id), headers=auth, json=changed)
        assert response.status_code == 422, response.text
        assert FAKE_KEY not in response.text
    _, other = account()
    _, unverified = account(False)
    assert client.get(url(run_id), headers=other).status_code == 404
    assert client.post(url(run_id), headers=other, json=body).status_code == 404
    assert client.post(url(run_id), headers=unverified, json=body).status_code == 403
    assert client.post(url(run_id), json=body).status_code == 401
    state = client.get(url(run_id), headers=auth).json()
    assert (
        state["submissions"] == []
        and state["completed_at"] is None
        and state["total_points"] == 0
    )
    assert len(provider["requests"]) == 1


def test_unclear_once_then_pending_and_unrelated_supplement(ready, provider):
    _, auth, run_id, config, *_ = ready
    provider["relevance"] = "unclear"
    body = payload(config)
    assert client.post(url(run_id), headers=auth, json=body).status_code == 202
    state = wait_submission(auth, run_id)
    first = state["submissions"][0]
    assert (
        first["neutral_clarification"]
        and state["completed_at"] is None
        and state["total_points"] == 0
    )
    body = payload(config, previous_submission_id=first["id"])
    for answer in body["answers"]:
        answer["reason"] = "这个材料里的信息，我还不明白。"
    assert client.post(url(run_id), headers=auth, json=body).status_code == 202
    state = wait_submission(auth, run_id)
    assert state["submissions"][-1]["kind"] == "clarification"
    assert not state["submissions"][-1]["neutral_clarification"]
    assert state["completed_at"] is None
    provider["relevance"] = "unrelated"
    body = payload(config, previous_submission_id=state["submissions"][-1]["id"])
    for answer in body["answers"]:
        answer["reason"] = "午饭准备吃饺子。"
    assert client.post(url(run_id), headers=auth, json=body).status_code == 202
    state = wait_submission(auth, run_id)
    assert (
        state["total_points"] == 0
        and state["submissions"][-1]["status"] == "needs_supplement"
    )
    provider["relevance"] = "related"
    body = payload(config, previous_submission_id=state["submissions"][-1]["id"])
    for answer in body["answers"]:
        answer["reason"] = "我不知道原因，需要查看这条请求的材料。"
    assert client.post(url(run_id), headers=auth, json=body).status_code == 202
    state = wait_submission(auth, run_id)
    assert state["total_points"] == 10
    assert state["submissions"][0]["answers"] == first["answers"]
    assert [s["kind"] for s in state["submissions"]] == [
        "original",
        "clarification",
        "supplement",
        "supplement",
    ]
    assert sum(s["neutral_clarification"] for s in state["submissions"]) == 1


def test_concurrent_duplicate_and_conflicting_submission(ready, provider):
    _, auth, run_id, config, process, _ = ready
    stop_worker(process)
    body = payload(config)
    barrier = Barrier(3)

    def post(value):
        barrier.wait()
        return client.post(url(run_id), headers=auth, json=value)

    with ThreadPoolExecutor(3) as pool:
        different = copy.deepcopy(body)
        different["request_id"] = str(uuid.uuid4())
        different["answers"][0]["reason"] = "另一设备的理由"
        results = [
            f.result()
            for f in [
                pool.submit(post, body),
                pool.submit(post, body),
                pool.submit(post, different),
            ]
        ]
    assert sorted(r.status_code for r in results) in [[202, 202, 409], [202, 409, 409]]
    state = client.get(url(run_id), headers=auth).json()
    assert len(state["submissions"]) == 1 and state["total_points"] == 0
    identity = uuid.UUID(state["submissions"][0]["id"])
    related = Relevance.model_validate(
        {"items": [{"judgment_id": f"j{i}", "status": "related"} for i in range(1, 4)]}
    )
    # Transaction seam: two actual PostgreSQL settlements cannot double-award.
    with ThreadPoolExecutor(2) as pool:
        for f in [pool.submit(settle, identity, related) for _ in range(2)]:
            f.result()
    state = client.get(url(run_id), headers=auth).json()
    assert state["total_points"] == 10
    assert len(provider["requests"]) == 1


@pytest.mark.parametrize(
    "mode,attempts", [("auth", 1), ("bad_relevance", 1), ("temporary", 3)]
)
def test_failures_retain_original_without_formal_fact(ready, provider, mode, attempts):
    _, auth, run_id, config, *_ = ready
    provider["mode"] = mode
    body = payload(config)
    assert client.post(url(run_id), headers=auth, json=body).status_code == 202
    state = wait_submission(auth, run_id)
    assert state["completed_at"] is None and state["total_points"] == 0
    assert state["submissions"][0]["answers"] == body["answers"]
    assert state["submissions"][0]["status"] == "failed"
    assert len(state["submissions"][0]["attempts"]) == attempts
    path = url(run_id) + f"/{body['request_id']}/retry"
    retry = client.post(path, headers=auth)
    if mode != "temporary":
        assert retry.status_code == 409
        return
    assert retry.status_code == 202
    state = wait_submission(auth, run_id)
    assert len(state["submissions"][0]["attempts"]) == 6
    assert client.post(path, headers=auth).status_code == 409
    assert (
        client.post(
            url(run_id), headers=auth, json={**body, "request_id": str(uuid.uuid4())}
        ).status_code
        == 202
    )
    assert len(provider["requests"]) == 7


def test_stop_inflight_and_explicit_retry_preserve_input(ready, provider):
    _, auth, run_id, config, *_ = ready
    provider["mode"] = "hold"
    provider["received"].clear()
    body = payload(config)
    assert client.post(url(run_id), headers=auth, json=body).status_code == 202
    assert provider["received"].wait(8)
    stopped = client.post(url(run_id) + f"/{body['request_id']}/stop", headers=auth)
    assert stopped.status_code == 200, stopped.text
    state = stopped.json()
    assert state["submissions"][0]["status"] == "stopped" and state["total_points"] == 0
    provider["release"].set()
    time.sleep(0.3)
    assert client.get(url(run_id), headers=auth).json()["completed_at"] is None
    assert len(provider["requests"]) == 2
    provider["mode"] = "ok"
    assert (
        client.post(
            url(run_id) + f"/{body['request_id']}/retry", headers=auth
        ).status_code
        == 202
    )
    state = wait_submission(auth, run_id)
    assert state["total_points"] == 10 and len(state["submissions"]) == 1
    assert state["submissions"][0]["answers"] == body["answers"]
    assert len(state["submissions"][0]["attempts"]) == 2


def test_settlement_transaction_failure_rolls_back_all_facts(ready):
    from sqlalchemy import event

    _, auth, run_id, config, process, _ = ready
    stop_worker(process)
    body = payload(config)
    assert client.post(url(run_id), headers=auth, json=body).status_code == 202

    def interrupt(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.startswith("INSERT INTO practice_award"):
            raise RuntimeError("controlled transaction failure")

    event.listen(engine, "after_cursor_execute", interrupt)
    try:
        with pytest.raises(RuntimeError, match="controlled transaction failure"):
            settle(
                uuid.UUID(body["request_id"]),
                Relevance.model_validate(
                    {
                        "items": [
                            {"judgment_id": f"j{i}", "status": "related"}
                            for i in range(1, 4)
                        ]
                    }
                ),
            )
    finally:
        event.remove(engine, "after_cursor_execute", interrupt)
    state = client.get(url(run_id), headers=auth).json()
    assert state["completed_at"] is None and state["total_points"] == 0
    assert state["submissions"][0]["status"] == "checking"


@pytest.mark.parametrize("settle_first", [False, True])
def test_stop_settle_race_is_one_transaction_order(ready, monkeypatch, settle_first):
    from threading import Event

    from sqlalchemy import event, text

    from app.training import submission_worker

    _, auth, run_id, config, process, _ = ready
    stop_worker(process)
    body = payload(config)
    assert client.post(url(run_id), headers=auth, json=body).status_code == 202
    identity = uuid.UUID(body["request_id"])
    entered, release = Event(), Event()
    related = Relevance.model_validate(
        {"items": [{"judgment_id": f"j{i}", "status": "related"} for i in range(1, 4)]}
    )
    original_lock = submission_worker.lock_owner

    def held_owner(session, user_id):
        user = original_lock(session, user_id)
        if not settle_first:
            entered.set()
            assert release.wait(5)
        return user

    def held_submission(
        _connection, _cursor, statement, parameters, _context, _executemany
    ):
        if (
            settle_first
            and statement.startswith("SELECT training_submission.")
            and "FOR UPDATE" in statement
            and parameters.get("id_1") == identity
        ):
            entered.set()
            assert release.wait(5)

    monkeypatch.setattr(submission_worker, "lock_owner", held_owner)
    event.listen(engine, "after_cursor_execute", held_submission)
    try:
        with ThreadPoolExecutor(2) as pool:
            settled = pool.submit(settle, identity, related)
            assert entered.wait(5)
            stopped = pool.submit(
                client.post, url(run_id) + f"/{identity}/stop", headers=auth
            )
            if not settle_first:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    with Session(engine) as session:
                        if session.get(Submission, identity).stop_requested:
                            break
                    time.sleep(0.02)
                else:
                    pytest.fail("stop intent did not commit")
            else:
                # Observe an actual PostgreSQL lock waiter, not merely an unfinished future.
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    with engine.connect() as connection:
                        waiting = connection.execute(
                            text(
                                "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND query LIKE '%training_submission%'"
                            )
                        ).scalar()
                    if waiting:
                        break
                    time.sleep(0.02)
                assert waiting
            release.set()
            settled.result(timeout=5)
            result = stopped.result(timeout=5)
        assert result.status_code == 200, result.text
        state = result.json()
        assert state["total_points"] == (10 if settle_first else 0)
        assert state["submissions"][0]["status"] == (
            "completed" if settle_first else "stopped"
        )
        assert bool(state["completed_at"]) == settle_first
    finally:
        release.set()
        event.remove(engine, "after_cursor_execute", held_submission)


def test_configuration_changed_before_dispatch_stops_old_submission(ready, provider):
    from tests.test_model_config import save

    _, auth, run_id, config, process, control = ready
    stop_worker(process)
    body = payload(config)
    assert client.post(url(run_id), headers=auth, json=body).status_code == 202
    new = save(
        auth,
        service_url=provider["url"],
        expected_version=config["version"],
        model_id="another-fake-model",
    ).json()
    process, _ = start_worker(control.parent, provider, run_id)
    try:
        state = wait_submission(auth, run_id)
        assert state["submissions"][0]["code"] == "configuration_revoked"
        assert state["total_points"] == 0 and len(provider["requests"]) == 1
        retry = payload(new, previous_submission_id=body["request_id"])
        assert client.post(url(run_id), headers=auth, json=retry).status_code == 202
        state = wait_submission(auth, run_id)
        assert state["total_points"] == 10
        assert state["submissions"][0]["answers"] == body["answers"]
        assert state["submissions"][1]["config_version"] == new["version"]
    finally:
        stop_worker(process)


def test_worker_kill_recovers_same_submission_budget(ready, provider):
    _, auth, run_id, config, process, control = ready
    provider["mode"] = "hold"
    provider["received"].clear()
    body = payload(config)
    assert client.post(url(run_id), headers=auth, json=body).status_code == 202
    assert provider["received"].wait(8)
    process.kill()
    process.wait(timeout=3)
    time.sleep(0.7)
    provider["mode"] = "ok"
    provider["release"].set()
    recovered, _ = start_worker(control.parent, provider, run_id)
    try:
        state = wait_submission(auth, run_id)
        assert state["total_points"] == 10
        assert (
            len(state["submissions"]) == 1
            and state["submissions"][0]["id"] == body["request_id"]
        )
        assert [a["code"] for a in state["submissions"][0]["attempts"]] == [
            "unknown",
            "ok",
        ]
        assert len(provider["requests"]) == 3
    finally:
        stop_worker(recovered)


@pytest.mark.parametrize("marker_unavailable", [False, True])
def test_unexpected_settlement_failure_has_safe_recovery(
    ready, provider, marker_unavailable
):
    from sqlalchemy import text

    from app.training.submission_worker import reconcile_failed_submissions

    _, auth, run_id, config, _, control = ready
    options = json.loads(control.read_text())
    control.write_text(
        json.dumps(
            {**options, "fail_settlement": True, "fail_marker": marker_unavailable}
        )
    )
    body = payload(config)
    assert client.post(url(run_id), headers=auth, json=body).status_code == 202
    if marker_unavailable:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            with engine.connect() as connection:
                failed = connection.execute(
                    text(
                        "SELECT j.status FROM procrastinate_jobs j JOIN training_submission s ON s.queue_job_id=j.id WHERE s.id=:id"
                    ),
                    {"id": uuid.UUID(body["request_id"])},
                ).scalar()
            if failed == "failed":
                break
            time.sleep(0.02)
        assert failed == "failed"
        assert (
            "PRIVATE_SUBMISSION_SENTINEL"
            not in (control.parent / "worker.log").read_text()
        )
        # Model is not called again merely because storage becomes available.
        reconcile_failed_submissions()
    state = wait_submission(auth, run_id)
    assert state["submissions"][0]["status"] == "failed"
    assert state["submissions"][0]["can_retry"]
    assert state["completed_at"] is None and state["total_points"] == 0
    assert len(provider["requests"]) == 2
    control.write_text(json.dumps(options))
    assert (
        client.post(
            url(run_id) + f"/{body['request_id']}/retry", headers=auth
        ).status_code
        == 202
    )
    state = wait_submission(auth, run_id)
    assert state["total_points"] == 10 and len(state["submissions"]) == 1
    assert len(state["submissions"][0]["attempts"]) == 2
