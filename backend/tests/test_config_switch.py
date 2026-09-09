"""Revocation ordering uses actual PostgreSQL locks, never simulated success."""

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlmodel import Session

from app.core.db import engine
from app.model_config.models import ModelConfig
from app.model_config.revocation import request_revocation
from app.model_config.service import current_for_result
from app.training.gate import call_credential
from tests.test_accounts import client
from tests.test_model_config import URL, account, save
from tests.test_practices import body as practice_body
from tests.test_practices import demo
from tests.test_practices import ready as practice_ready  # noqa: E402,F401
from tests.test_practices import url as practice_url
from tests.test_project import provider as project_test_provider
from tests.test_training import provider as training_provider  # noqa: E402,F401

guided_ready = practice_ready
provider = training_provider
project_provider = project_test_provider


@pytest.mark.parametrize("remove", [False, True])
def test_switch_cancels_real_permission_holder_before_success(remove):
    owner, auth = account()
    version = uuid.UUID(save(auth).json()["version"])

    async def run():
        entered, cancelled = asyncio.Event(), asyncio.Event()

        async def held_call():
            async with call_credential(owner, version):
                entered.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    raise

        task = asyncio.create_task(held_call())
        await asyncio.wait_for(entered.wait(), 3)

        def change():
            return (
                client.delete(
                    URL, headers=auth, params={"expected_version": str(version)}
                )
                if remove
                else save(auth, expected_version=str(version))
            )

        result = await asyncio.wait_for(asyncio.to_thread(change), 3)
        assert result.status_code == (204 if remove else 200)
        assert cancelled.is_set()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(HTTPException):
            async with call_credential(owner, version):
                pytest.fail("revoked version dispatched")

    asyncio.run(run())


def test_invalid_replacement_does_not_revoke_and_interrupted_switch_stays_revoked(
    monkeypatch,
):
    from app.model_config import routes

    owner, auth = account()
    version = save(auth).json()["version"]
    for change in (
        {"disclosure_accepted": False},
        {"service_url": "https://other.example.com", "api_key": None},
        {"api_key": "bad key"},
    ):
        assert save(auth, expected_version=version, **change).status_code == 422
        assert not client.get(URL, headers=auth).json()["revoked"]
    lock = routes.lock_owner

    def crash(*_args):
        raise HTTPException(503, "controlled interruption after durable intent")

    monkeypatch.setattr(routes, "lock_owner", crash)
    assert save(auth, expected_version=version).status_code == 503
    assert client.get(URL, headers=auth).json()["revoked"]
    with Session(engine) as session, pytest.raises(HTTPException):
        current_for_result(session, owner, uuid.UUID(version))
    monkeypatch.setattr(routes, "lock_owner", lock)
    recovered = save(auth, expected_version=version)
    assert recovered.status_code == 200 and not recovered.json()["revoked"]


def test_concurrent_switch_cannot_revoke_winning_new_version(monkeypatch):
    from app.model_config import routes

    owner, auth = account()
    version = save(auth).json()["version"]
    reached, release = Event(), Event()
    real = routes.request_revocation
    calls = []

    def held(*args):
        real(*args)
        calls.append(args)
        if len(calls) == 1:
            reached.set()
            assert release.wait(5)

    monkeypatch.setattr(routes, "request_revocation", held)
    with ThreadPoolExecutor(1) as pool:
        loser = pool.submit(save, auth, expected_version=version)
        try:
            assert reached.wait(3)
            winner = save(auth, expected_version=version, model_id="winning-model")
            assert winner.status_code == 200
        finally:
            release.set()
        assert loser.result(3).status_code == 409
    assert client.get(URL, headers=auth).json() == winner.json()
    with pytest.raises(HTTPException):
        request_revocation(owner, uuid.UUID(version))
    assert not client.get(URL, headers=auth).json()["revoked"]


def test_result_commit_and_revocation_share_actual_config_row_lock():
    owner, auth = account()
    version = uuid.UUID(save(auth).json()["version"])
    # A result holding the commit guard wins first: revocation cannot commit.
    with Session(engine) as result:
        current_for_result(result, owner, version)
        with Session(engine) as revoke, pytest.raises(OperationalError):
            revoke.execute(text("SET LOCAL lock_timeout='100ms'"))
            revoke.execute(
                text("UPDATE model_config SET revoked=true WHERE user_id=:owner"),
                {"owner": owner},
            )
        result.commit()
    request_revocation(owner, version)
    # Revocation winning first prevents a result from reaching its commit point.
    with Session(engine) as result, pytest.raises(HTTPException):
        current_for_result(result, owner, version)
    with Session(engine) as session:
        assert session.get(ModelConfig, owner).revoked


@pytest.mark.parametrize(
    "kind", ["generation", "help", "submission", "practice", "evaluation"]
)
def test_inflight_worker_switch_keeps_partial_usage_and_completed_case(
    guided_ready, provider, kind
):
    import json
    import time
    from pathlib import Path

    from tests.test_concepts import publish, receipt, request
    from tests.test_evaluations import start as start_evaluation
    from tests.test_submissions import wait_submission

    auth, run_id, config, _, control = guided_ready
    run_path = f"/api/v1/training/tasks/{run_id}"
    original = client.get(run_path, headers=auth).json()["case"]
    submitted = practice_body(config)
    submitted["answers"] = [
        {
            "judgment_id": j["id"],
            "value": [0, 1, 2]
            if j["kind"] == "order"
            else "需要查证"
            if j["kind"] == "prediction"
            else 1,
            "reason": "需要核对实际处理记录",
        }
        for j in original["judgments"]
    ]
    path = run_path + "/submissions"
    if kind == "evaluation":
        assert client.post(path, headers=auth, json=submitted).status_code == 202
        assert wait_submission(auth, run_id)["awarded_points"] == 10
        path = run_path + "/evaluation"
    elif kind == "practice":
        help_id = demo(guided_ready)
        receipt(auth, run_id, publish(auth, run_id, help_id))
        path = practice_url(run_id, help_id)
        submitted = practice_body(config)
    before = len(provider["requests"])
    options = json.loads(control.read_text())
    options["observe_usage"] = True
    control.write_text(json.dumps(options))
    provider["mode"] = "partial_usage"
    if kind == "generation":
        result = client.post(
            "/api/v1/training/random",
            headers=auth,
            json={
                "disclosure_accepted": True,
                "expected_config_version": config["version"],
                "previous_run_id": run_id,
            },
        )
        assert result.status_code == 202, result.text
        path = f"/api/v1/training/tasks/{result.json()['id']}"
    elif kind == "help":
        item, _ = request(auth, run_id, config)
        path = run_path + "/help/" + item["id"]
    elif kind == "evaluation":
        start_evaluation(auth, run_id, config)
    else:
        assert client.post(path, headers=auth, json=submitted).status_code == 202
    deadline = time.monotonic() + 8
    while not Path(str(control) + ".usage_received").exists():
        assert time.monotonic() < deadline, "consumer did not receive partial usage"
        time.sleep(0.02)
    changed = (
        client.delete(URL, headers=auth, params={"expected_version": config["version"]})
        if kind in {"help", "evaluation"}
        else save(
            auth, expected_version=config["version"], service_url=config["service_url"]
        )
    )
    assert changed.status_code in {200, 204}, changed.text
    provider["release"].set()
    deadline = time.monotonic() + 6
    while True:
        usage = client.get(URL + "/usage", headers=auth)
        assert usage.status_code == 200, usage.text
        calls = usage.json()["calls"]
        cancelled = [c for c in calls if c["code"] == "cancelled"]
        if cancelled:
            break
        assert time.monotonic() < deadline, calls
        time.sleep(0.02)
    assert len(cancelled) == 1
    call = cancelled[0]
    assert call["kind"] == kind
    assert (
        call["prompt_tokens"] == 11
        and call["total_tokens"] == 20
        and call["completion_tokens"] is None
    )
    assert call["config_version"] == config["version"]
    assert len(provider["requests"]) == before + 1
    result = (
        client.get(path, headers=auth).json()
        if kind != "help"
        else next(
            h
            for h in client.get(run_path + "/help", headers=auth).json()
            if h["id"] == item["id"]
        )
    )
    if kind in {"submission", "practice"}:
        result = (result["records"] if kind == "practice" else result)["submissions"][
            -1
        ]
    assert result["status"] == "stopped", result
    assert client.get(run_path, headers=auth).json()["case"] == original
    assert client.get(URL + "/usage", headers=auth).json() == usage.json()
    assert usage.json()["totals"]["completion_tokens"]["unknown_calls"] == 1
    assert client.get(URL + "/usage", headers=account()[1]).json()["calls"] == []


def test_project_switch_cancels_transport_preserves_checkpoint_and_usage(
    tmp_path, project_provider
):
    import time

    from tests.test_project import start_project, start_worker, stop_worker

    project_provider["mode"] = "partial_usage"
    auth, identity = start_project(project_provider)
    config = client.get(URL, headers=auth).json()
    process, control = start_worker(
        tmp_path, project_provider, identity, observe_usage=True
    )
    try:
        deadline = time.monotonic() + 8
        while not control.with_name(control.name + ".usage_received").exists():
            assert time.monotonic() < deadline
            time.sleep(0.02)
        path = f"/api/v1/projects/{identity}"
        checkpoint = client.get(path, headers=auth).json()["project_map"]
        assert (
            save(
                auth,
                expected_version=config["version"],
                service_url=config["service_url"],
            ).status_code
            == 200
        )
        project_provider["release"].set()
        deadline = time.monotonic() + 6
        while True:
            usage = client.get(URL + "/usage", headers=auth).json()
            if usage["calls"][0]["code"] == "cancelled":
                break
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert usage["calls"][0]["prompt_tokens"] == 11
        assert usage["calls"][0]["completion_tokens"] is None
        result = client.get(path, headers=auth).json()
        assert result["status"] == "stopped" and result["project_map"] == checkpoint
        assert len(project_provider["requests"]) == 1
    finally:
        stop_worker(process)


def test_probe_usage_is_durable_owned_and_retry_attempts_are_not_summed_twice(
    monkeypatch,
):
    from app.model_config import routes
    from app.model_config.connection import ProbeError
    from tests.test_model_config import body

    _, auth = account()
    attempts = []

    async def request(*_args):
        attempts.append(1)
        if len(attempts) == 1:
            raise ProbeError(
                "timeout",
                "controlled retry",
                True,
                {"prompt_tokens": 0, "total_tokens": 2},
            )
        return ["chosen-model"], {
            "prompt_tokens": 3,
            "completion_tokens": 4,
            "total_tokens": 7,
        }

    monkeypatch.setattr(routes, "request_once", request)
    monkeypatch.setattr(routes, "BACKOFF_SECONDS", (0, 0))
    response = client.post(URL + "/probe/models", headers=auth, json=body())
    assert response.status_code == 200 and response.json()["ok"]
    usage = client.get(URL + "/usage", headers=auth)
    assert usage.status_code == 200 and usage.headers["cache-control"] == "no-store"
    report = usage.json()
    assert len(report["calls"]) == 2
    assert len({c["id"] for c in report["calls"]}) == 2
    assert len({c["task_id"] for c in report["calls"]}) == 1
    assert report["totals"] == {
        "prompt_tokens": {"known": 3, "unknown_calls": 0},
        "completion_tokens": {"known": 4, "unknown_calls": 1},
        "total_tokens": {"known": 9, "unknown_calls": 0},
    }
    assert client.get(URL + "/usage", headers=auth).json() == report
    assert client.get(URL + "/usage", headers=account()[1]).json()["calls"] == []
    assert client.get(URL + "/usage").status_code == 401


@pytest.mark.parametrize("revoke_first", [True, False])
def test_real_settlement_orders_award_commit_against_revocation(
    guided_ready, monkeypatch, revoke_first
):
    from app.training import submission_worker
    from app.training.submission_models import PracticeAward
    from app.training.submission_schema import Relevance
    from tests.test_training import stop_worker

    auth, run_id, config, process, _ = guided_ready
    help_id = demo(guided_ready)
    from tests.test_concepts import publish, receipt

    receipt(auth, run_id, publish(auth, run_id, help_id))
    stop_worker(process)
    submitted = practice_body(config)
    assert (
        client.post(
            practice_url(run_id, help_id), headers=auth, json=submitted
        ).status_code
        == 202
    )
    with Session(engine) as session:
        from app.training.models import TrainingRun

        owner = session.get(TrainingRun, uuid.UUID(run_id)).user_id
    reached, release = Event(), Event()
    real = submission_worker.current_for_result

    def gate(*args):
        if not revoke_first:
            result = real(*args)
        reached.set()
        assert release.wait(5)
        return real(*args) if revoke_first else result

    monkeypatch.setattr(submission_worker, "current_for_result", gate)
    relevance = Relevance.model_validate(
        {"items": [{"judgment_id": "j1", "status": "related"}]}
    )
    with ThreadPoolExecutor(1) as pool:
        settling = pool.submit(
            submission_worker.settle, uuid.UUID(submitted["request_id"]), relevance
        )
        try:
            assert reached.wait(3)
            if revoke_first:
                request_revocation(owner, uuid.UUID(config["version"]))
            else:
                with Session(engine) as session, pytest.raises(OperationalError):
                    session.execute(text("SET LOCAL lock_timeout='100ms'"))
                    session.execute(
                        text(
                            "UPDATE model_config SET revoked=true WHERE user_id=:owner"
                        ),
                        {"owner": owner},
                    )
        finally:
            release.set()
        if revoke_first:
            with pytest.raises(HTTPException):
                settling.result(3)
        else:
            assert settling.result(3)
            request_revocation(owner, uuid.UUID(config["version"]))
    with Session(engine) as session:
        assert bool(session.get(PracticeAward, uuid.UUID(run_id))) is not revoke_first


def test_probe_cancellation_records_observed_usage_and_does_not_retry(monkeypatch):
    from app.model_config import routes
    from app.model_config.connection import CancelledCall
    from tests.test_model_config import body

    _, auth = account()
    config = save(auth).json()
    entered = Event()
    calls = []

    async def request(*_args):
        calls.append(1)
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise CancelledCall(
                {"prompt_tokens": 11, "completion_tokens": None, "total_tokens": 20}
            ) from None

    monkeypatch.setattr(routes, "request_once", request)
    with ThreadPoolExecutor(1) as pool:
        probe = pool.submit(client.post, URL + "/probe/test", headers=auth, json=body())
        assert entered.wait(3)
        assert save(auth, expected_version=config["version"]).status_code == 200
        result = probe.result(3)
    assert result.status_code == 200 and result.json()["code"] == "cancelled"
    assert calls == [1]
    usage = client.get(URL + "/usage", headers=auth).json()
    assert len(usage["calls"]) == 1
    assert usage["calls"][0]["prompt_tokens"] == 11
    assert usage["totals"]["completion_tokens"] == {"known": 0, "unknown_calls": 1}


@pytest.mark.parametrize("stage", ["before_http", "before_accept"])
def test_switch_blocks_undispatched_and_late_generation(provider, tmp_path, stage):
    import json
    import time
    from pathlib import Path

    from app.training import worker
    from tests.test_training import start_run, start_worker, stop_worker

    owner, auth, run_id = start_run(provider)
    config = client.get(URL, headers=auth).json()
    process, control = start_worker(
        tmp_path, provider, run_id, **{stage: True, "observe_accept": True}
    )
    try:
        marker = ".blocked" if stage == "before_http" else ".accepting"
        deadline = time.monotonic() + 8
        while not Path(str(control) + marker).exists():
            assert time.monotonic() < deadline
            time.sleep(0.02)
        if stage == "before_accept":
            with ThreadPoolExecutor(1) as pool:
                saving = pool.submit(
                    save,
                    auth,
                    expected_version=config["version"],
                    service_url=config["service_url"],
                )
                try:
                    deadline = time.monotonic() + 5
                    while True:
                        with Session(engine) as session:
                            row = session.get(ModelConfig, owner)
                            if row.revoked:
                                break
                        assert time.monotonic() < deadline
                        time.sleep(0.02)
                    assert not saving.done()
                finally:
                    options = json.loads(control.read_text())
                    options[stage] = False
                    control.write_text(json.dumps(options))
                assert saving.result(5).status_code == 200
        else:
            assert (
                save(
                    auth,
                    expected_version=config["version"],
                    service_url=config["service_url"],
                ).status_code
                == 200
            )
            options = json.loads(control.read_text())
            options[stage] = False
            control.write_text(json.dumps(options))
        if stage == "before_accept":
            deadline = time.monotonic() + 5
            while not Path(str(control) + ".accept_finished").exists():
                assert time.monotonic() < deadline
                time.sleep(0.02)
        result = client.get(f"/api/v1/training/tasks/{run_id}", headers=auth).json()
        assert result["status"] == "stopped" and result["case"] is None
        assert result["config_version"] == config["version"]
        assert len(provider["requests"]) == (1 if stage == "before_accept" else 0)
        if stage == "before_accept":
            assert result["attempts"][0]["prompt_tokens"] == 11
        stop_worker(process)
        asyncio.run(worker.process(uuid.UUID(run_id)))
        assert len(provider["requests"]) == (1 if stage == "before_accept" else 0)
    finally:
        options = json.loads(control.read_text())
        options[stage] = False
        control.write_text(json.dumps(options))
        stop_worker(process)


@pytest.mark.parametrize("failure_first", [False, True])
def test_switch_preserves_real_provider_failure(provider, failure_first):
    from app.training.worker import finish
    from tests.test_training import start_run

    owner, auth, run_id = start_run(provider)
    config = client.get(URL, headers=auth).json()
    version = uuid.UUID(config["version"])
    if not failure_first:
        request_revocation(owner, version)
    finish(uuid.UUID(run_id), "invalid_response", "模型响应不合法")
    assert save(auth, expected_version=str(version)).status_code == 200
    result = client.get(f"/api/v1/training/tasks/{run_id}", headers=auth).json()
    assert result["status"] == "failed" and result["code"] == "invalid_response"
    finish(uuid.UUID(run_id), "cancelled", "迟到取消不得覆盖真实失败")
    assert client.get(f"/api/v1/training/tasks/{run_id}", headers=auth).json() == result
    assert result["case"] is None and result["attempts"] == []
    assert provider["requests"] == []


def test_probe_cancel_after_response_preserves_already_received_usage(monkeypatch):
    from contextlib import asynccontextmanager

    from app.model_config import routes
    from tests.test_model_connection import body

    _, auth = account()

    @asynccontextmanager
    async def cancelled_exit(*_):
        yield
        raise asyncio.CancelledError

    async def received(*_):
        return [], {"prompt_tokens": 11, "completion_tokens": 9, "total_tokens": 20}

    monkeypatch.setattr(routes, "call_permission", cancelled_exit)
    monkeypatch.setattr(routes, "request_once", received)
    result = client.post(URL + "/probe/test", headers=auth, json=body())
    assert result.status_code == 200 and result.json()["code"] == "cancelled"
    usage = client.get(URL + "/usage", headers=auth).json()
    assert len(usage["calls"]) == 1
    assert usage["calls"][0]["prompt_tokens"] == 11
    assert usage["calls"][0]["completion_tokens"] == 9
    assert usage["calls"][0]["total_tokens"] == 20


def test_revoke_after_candidate_commit_preserves_complete_result(provider, tmp_path):
    import json
    import time
    from pathlib import Path

    from tests.test_training import start_run, start_worker, stop_worker

    owner, auth, run_id = start_run(provider)
    config = client.get(URL, headers=auth).json()
    process, control = start_worker(
        tmp_path, provider, run_id, after_accept=True, observe_finish=True
    )
    try:
        deadline = time.monotonic() + 8
        while not Path(str(control) + ".accepted").exists():
            assert time.monotonic() < deadline, "candidate did not commit"
            time.sleep(0.02)
        endpoint = f"/api/v1/training/tasks/{run_id}"
        before = client.get(endpoint, headers=auth).json()
        assert before["status"] == "completed" and before["code"] == "ready"
        assert before["case"] is not None
        assert before["attempts"] == [
            {
                "number": 1,
                "code": "ok",
                "prompt_tokens": 11,
                "completion_tokens": 9,
                "total_tokens": 20,
            }
        ]
        with ThreadPoolExecutor(1) as pool:
            saving = pool.submit(save, auth, expected_version=config["version"])
            try:
                deadline = time.monotonic() + 5
                while True:
                    with Session(engine) as session:
                        revoked = session.get(ModelConfig, owner).revoked
                    if revoked and Path(str(control) + ".accept_cancelled").exists():
                        break
                    assert time.monotonic() < deadline, "revocation must reach actual acceptance waiter"
                    time.sleep(.02)
                assert not saving.done()
            finally:
                options = json.loads(control.read_text())
                options["after_accept"] = False
                control.write_text(json.dumps(options))
            assert saving.result(5).status_code == 200
        deadline = time.monotonic() + 5
        while not Path(str(control) + ".finished").exists():
            assert time.monotonic() < deadline, "cancel finish did not settle"
            time.sleep(0.02)
        assert client.get(endpoint, headers=auth).json() == before
        assert len(provider["requests"]) == 1
    finally:
        options = json.loads(control.read_text())
        options["after_accept"] = False
        control.write_text(json.dumps(options))
        stop_worker(process)
