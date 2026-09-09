"""Real PostgreSQL / independent worker / controlled TLS, never paid models."""

import asyncio
import json
import threading
import time
import uuid

import pytest
from sqlmodel import Session

from app.core.db import engine
from app.training.independent_models import IndependentWork
from app.training.models import TrainingRun
from app.training.queue import queue
from tests import test_guided
from tests.test_accounts import client
from tests.test_concepts import receipt
from tests.test_concepts import request as request_help
from tests.test_concepts import wait as wait_help
from tests.test_evaluations import grading
from tests.test_evaluations import start as start_evaluation
from tests.test_evaluations import wait as wait_evaluation
from tests.test_independent_novelty import variant
from tests.test_model_config import account, save
from tests.test_practices import guided_coach
from tests.test_submissions import wait_submission
from tests.test_training import provider as training_provider
from tests.test_training import start_worker, stop_worker, wait_run

provider = training_provider
frozen = test_guided.frozen


@pytest.fixture
def origin(provider, frozen):
    case, sources = frozen
    owner, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    with Session(engine) as session:
        run = TrainingRun(
            user_id=owner,
            config_version=uuid.UUID(config["version"]),
            destination=provider["url"],
            model_id=config["model_id"],
            target=case.target.model_dump(),
            selection={"catalog_version": case.catalog_version, "goal": "提交证据"},
            sources=[s.model_dump() for s in sources],
            candidate=case.model_dump(),
            status="completed",
            code="ready",
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        origin_id = run.id
    new, comparison = variant(case, origin_id)
    provider["comparison_received"] = threading.Event()
    provider["comparison_release"] = threading.Event()

    def reply(payload):
        context = json.loads(payload["messages"][1]["content"])
        if "new" in context:
            provider["comparison_received"].set()
            if provider.get("hold_comparison"):
                assert provider["comparison_release"].wait(10)
            return {"comparisons": [comparison.model_dump(mode="json")]}
        return new.model_dump()

    provider["candidate"] = reply
    return auth, origin_id, config, new


def start_check(origin):
    auth, origin_id, config, _ = origin
    body = {
        "request_id": str(uuid.uuid4()),
        "expected_config_version": config["version"],
        "disclosure_accepted": True,
    }
    result = client.post(
        f"/api/v1/training/tasks/{origin_id}/independent", headers=auth, json=body
    )
    assert result.status_code == 202, result.text
    return result.json()["id"], body


def test_private_comparison_then_real_two_call_acceptance(tmp_path, provider, origin):
    auth, origin_id, config, _ = origin
    run_id, body = start_check(origin)
    submitted = client.post(
        f"/api/v1/training/tasks/{run_id}/submissions",
        headers=auth,
        json={
            "request_id": str(uuid.uuid4()),
            "expected_config_version": config["version"],
            "disclosure_accepted": True,
            "answers": [{"judgment_id": "j1", "value": 0, "reason": "自己的判断理由"}],
        },
    )
    assert submitted.status_code == 409, submitted.text
    provider["hold_comparison"] = True
    process, _ = start_worker(tmp_path, provider, run_id)
    try:
        assert provider["comparison_received"].wait(15)
        pending = client.get(f"/api/v1/training/tasks/{run_id}", headers=auth)
        assert pending.json()["case"] is None
        assert (
            "PRIVATE_HELP" not in pending.text
            and "before_reasoning" not in pending.text
        )
        provider["comparison_release"].set()
        result = wait_run(auth, run_id).json()
        assert result["status"] == "completed", result
        assert result["launch_mode"] == result["current_mode"] == "independent"
        assert result["origin_id"] == str(origin_id)
        assert len(result["attempts"]) == 2
        assert all(a["total_tokens"] == 20 for a in result["attempts"])
        assert len(provider["requests"]) == 2
        sent = provider["requests"][1]["messages"][1]["content"]
        assert "help_boundary" not in sent and "answers" not in sent
        replay = client.post(
            f"/api/v1/training/tasks/{origin_id}/independent", headers=auth, json=body
        )
        assert replay.json()["id"] == run_id
        assert len(provider["requests"]) == 2
        with Session(engine) as session:
            work = session.get(IndependentWork, uuid.UUID(run_id))
            assert work.novelty["assessment"]["semantic_reliability"] == "unverified"
    finally:
        provider["comparison_release"].set()
        stop_worker(process)


@pytest.mark.parametrize(
    "modes,expected,calls",
    [
        (
            ["temporary", "temporary", "ok", "temporary", "temporary", "ok"],
            "completed",
            6,
        ),
        (["empty", "ok", "ok"], "completed", 3),
        (["empty", "empty"], "failed", 2),
        (["ok", "empty", "empty"], "failed", 3),
        (["auth"], "failed", 1),
    ],
)
def test_phase_budgets_malformed_correction_and_transient_backoff(
    tmp_path, provider, origin, modes, expected, calls
):
    auth, *_ = origin
    run_id, _ = start_check(origin)
    provider["modes"] = modes
    process, _ = start_worker(tmp_path, provider, run_id)
    try:
        result = wait_run(auth, run_id).json()
        assert result["status"] == expected, result
        assert len(provider["requests"]) == calls
        assert len(result["attempts"]) == calls
        if expected == "failed":
            assert result["case"] is None
    finally:
        stop_worker(process)


@pytest.fixture
def checked(tmp_path, provider, origin):
    auth, _, config, _ = origin
    run_id, _ = start_check(origin)
    provider["coach"] = guided_coach
    provider["grading"] = controlled_grading
    process, _ = start_worker(tmp_path, provider, run_id)
    try:
        assert wait_run(auth, run_id).json()["status"] == "completed"
        yield auth, run_id, config
    finally:
        stop_worker(process)


def controlled_grading(context):
    result = grading(context)
    material = context["task"]["evidence"][0]
    fact, value = next(iter(material["facts"].items()))
    for item in result["items"]:
        item["grounding"][0].update(fact=fact, value=value)
        item["reason_claims"][0]["interpreted_fact_value"] = value
    return result


def evaluate(checked):
    auth, run_id, config = checked
    submitted = client.post(
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
    assert submitted.status_code == 202, submitted.text
    state = wait_submission(auth, run_id)
    assert state["completed_at"] and state["awarded_points"] == 10
    start_evaluation(auth, run_id, config)
    result = wait_evaluation(auth, run_id)
    assert result["status"] == "completed", result
    return result


def confirmed_publication(checked):
    auth, run_id, config = checked
    item, _ = request_help(auth, run_id, config, kind="hint")
    ready = wait_help(auth, run_id, item["id"])
    assert ready["status"] == "ready", ready
    assert ready["requires_independent_confirmation"]
    root = f"/api/v1/training/tasks/{run_id}/help/{item['id']}"
    blocked = client.post(root + "/deliver", headers=auth)
    assert blocked.status_code == 409 and "已有修为不变" in blocked.text
    consent = client.post(
        root + "/confirm",
        headers=auth,
        json={"content_hash": ready["content_hash"], "accepted": True},
    )
    assert consent.status_code == 200, consent.text
    assert (
        client.get(f"/api/v1/training/tasks/{run_id}", headers=auth).json()[
            "current_mode"
        ]
        == "independent"
    )
    publication = client.post(
        root + "/deliver", headers=auth, json={"confirmation_id": consent.json()["id"]}
    )
    assert publication.status_code == 200, publication.text
    assert (
        client.get(f"/api/v1/training/tasks/{run_id}", headers=auth).json()[
            "current_mode"
        ]
        == "independent"
    )
    return publication.json()


@pytest.mark.parametrize("timing", ["before", "late_receipt", "after_freeze"])
def test_actual_delivery_and_original_exposure_determine_frozen_qualification(
    checked, provider, timing
):
    auth, run_id, _ = checked
    if timing == "after_freeze":
        assert evaluate(checked)["independent_outcome"] == "independent_pass_candidate"
    publication = confirmed_publication(checked)
    if timing == "before":
        assert receipt(auth, run_id, publication).status_code == 200
    if timing != "after_freeze":
        result = evaluate(checked)
        assert result["independent_outcome"] == (
            "practice" if timing == "before" else "pending_delivery"
        )
    calls = len(provider["requests"])
    if timing != "before":
        assert (
            client.delete(
                "/api/v1/model-config",
                headers=auth,
                params={"expected_version": checked[2]["version"]},
            ).status_code
            == 204
        )
        assert receipt(auth, run_id, publication).status_code == 200
    final = client.get(
        f"/api/v1/training/tasks/{run_id}/evaluation", headers=auth
    ).json()
    assert final["independent_outcome"] == (
        "independent_pass_candidate" if timing == "after_freeze" else "practice"
    )
    assert len(provider["requests"]) == calls
    assert (
        client.get(f"/api/v1/training/tasks/{run_id}", headers=auth).json()[
            "current_mode"
        ]
        == "practice"
    )


def wait_until(predicate):
    end = time.monotonic() + 15
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("controlled worker barrier did not arrive")


def test_permanent_outcome_recorded_before_crash_never_dispatches_again(
    tmp_path, provider, origin
):
    auth, *_ = origin
    run_id, _ = start_check(origin)
    provider["mode"] = "auth"
    process, control = start_worker(
        tmp_path, provider, run_id, after_training_record="authentication"
    )
    try:
        marker = type(control)(str(control) + ".training_recorded")
        wait_until(marker.exists)
        assert len(provider["requests"]) == 1
        process.kill()
        process.wait()

        async def stalled():
            async with queue.open_async():
                end = time.monotonic() + 10
                while time.monotonic() < end:
                    jobs = await queue.job_manager.get_stalled_jobs(
                        task_name="training.generate", seconds_since_heartbeat=0.5
                    )
                    if any(j.task_kwargs.get("run_id") == run_id for j in jobs):
                        return
                    await asyncio.sleep(0.02)
                raise AssertionError("killed worker did not become stalled")

        asyncio.run(stalled())
        process, _ = start_worker(tmp_path, provider, run_id)
        result = wait_run(auth, run_id).json()
        assert result["status"] == "failed" and result["code"] == "authentication", (
            result
        )
        assert len(result["attempts"]) == len(provider["requests"]) == 1
        assert result["attempts"][0]["code"] == "authentication"
    finally:
        if process.poll() is None:
            options = json.loads(control.read_text())
            options.pop("after_training_record", None)
            control.write_text(json.dumps(options))
        stop_worker(process)


def test_stop_before_dispatch_then_retry_preserves_budget_and_old_job_cannot_overwrite(
    tmp_path, provider, origin
):
    from app.training.worker import finish, finish_stop

    auth, *_ = origin
    run_id, _ = start_check(origin)
    process, control = start_worker(tmp_path, provider, run_id, before_http=True)
    try:
        wait_until(type(control)(str(control) + ".blocked").exists)
        with Session(engine) as session:
            old_job = session.get(TrainingRun, uuid.UUID(run_id)).queue_job_id
        stopped = client.post(f"/api/v1/training/tasks/{run_id}/stop", headers=auth)
        assert stopped.status_code == 200 and stopped.json()["status"] == "stopped"
        assert len(provider["requests"]) == 0
        options = json.loads(control.read_text())
        options["before_http"] = False
        control.write_text(json.dumps(options))
        retry = client.post(
            f"/api/v1/training/tasks/{run_id}/independent/retry", headers=auth
        )
        assert retry.status_code == 202, retry.text
        finish_stop(uuid.UUID(run_id), old_job)
        finish(uuid.UUID(run_id), "cancelled", "old delayed finish", old_job)
        result = wait_run(auth, run_id).json()
        assert result["status"] == "completed", result
        assert len(result["attempts"]) == 3
        assert len(provider["requests"]) == 2
        assert result["attempts"][0]["code"] in {"unknown", "cancelled"}
    finally:
        stop_worker(process)


def test_unknown_history_exits_without_a_call_and_same_case_cannot_be_washed(
    checked, provider
):
    auth, origin_id, config = checked
    publication = confirmed_publication(checked)
    calls = len(provider["requests"])
    response = client.post(
        f"/api/v1/training/tasks/{origin_id}/independent",
        headers=auth,
        json={
            "request_id": str(uuid.uuid4()),
            "expected_config_version": config["version"],
            "disclosure_accepted": True,
        },
    )
    assert response.status_code == 202, response.text
    identity = response.json()["id"]
    result = wait_run(auth, identity).json()
    assert result["code"] == "unresolved_history_delivery" and result["case"] is None
    assert result["attempts"] == [] and len(provider["requests"]) == calls
    assert receipt(auth, origin_id, publication).status_code == 200
    assert (
        client.post(
            f"/api/v1/training/tasks/{identity}/independent/retry", headers=auth
        ).status_code
        == 202
    )
    result = wait_run(auth, identity).json()
    assert result["status"] == "failed" and result["code"] == "no_qualified_case", (
        result
    )
    assert len(provider["requests"]) == calls + 2
    assert result["case"] is None


def test_full_history_resource_exit_does_not_silently_trim_or_call_model(
    tmp_path, provider, origin
):
    from app.training.history_protocol import CapacityError, freeze_history
    from app.training.schema import Candidate

    auth, origin_id, *_ = origin
    with Session(engine) as session:
        original = session.get(TrainingRun, origin_id)
        complete = {}
        for number in range(600):
            data = original.candidate | {
                "task": "请核对材料中的执行证据。" * 380 + str(number)
            }
            case = Candidate.model_validate_json(json.dumps(data))
            identity = uuid.uuid4()
            complete[identity] = case
            session.add(
                TrainingRun(
                    id=identity,
                    user_id=original.user_id,
                    config_version=original.config_version,
                    destination=original.destination,
                    model_id=original.model_id,
                    target=original.target,
                    selection=original.selection,
                    sources=original.sources,
                    candidate=case.model_dump(mode="json"),
                    status="completed",
                )
            )
        # Every complete snapshot is valid and distinct after exact-value
        # reference sharing. This exercises the new real 8MiB storage boundary,
        # not the intentionally removed legacy 96KiB restriction.
        assert len({case.model_dump_json() for case in complete.values()}) == 600
        with pytest.raises(CapacityError, match="history_snapshot_exceeds_8MiB"):
            freeze_history(complete)
        session.commit()
    identity, _ = start_check(origin)
    process, _ = start_worker(tmp_path, provider, identity)
    try:
        result = wait_run(auth, identity).json()
        assert result["code"] == "comparison_capacity", result
        assert result["attempts"] == [] and result["case"] is None
        assert provider["requests"] == []
        assert "完整历史" in result["message"] and "未交付新题" in result["message"]
    finally:
        stop_worker(process)


def test_encoded_secret_in_comparison_never_becomes_public_or_persistent_output(
    tmp_path, provider, origin
):
    from tests.test_model_config import FAKE_KEY

    auth, *_ = origin
    original = provider["candidate"]

    def unsafe(payload):
        value = original(payload)
        if "comparisons" in value:
            value["comparisons"][0]["changes"][0]["explanation"] = FAKE_KEY
        return value

    provider["candidate"], provider["escaped_output"] = unsafe, True
    identity, _ = start_check(origin)
    process, _ = start_worker(tmp_path, provider, identity)
    try:
        result = wait_run(auth, identity).json()
        assert result["status"] == "failed" and result["case"] is None
        assert len(provider["requests"]) == 3
        assert all(a["total_tokens"] == 20 for a in result["attempts"])
        assert FAKE_KEY not in json.dumps(result)
        with Session(engine) as session:
            assert session.get(IndependentWork, uuid.UUID(identity)).novelty is None
    finally:
        stop_worker(process)


def test_config_revocation_before_dispatch_prevents_request_and_old_retry(
    tmp_path, provider, origin
):
    auth, _, config, _ = origin
    identity, _ = start_check(origin)
    process, control = start_worker(tmp_path, provider, identity, before_http=True)
    try:
        wait_until(type(control)(str(control) + ".blocked").exists)
        removed = client.delete(
            "/api/v1/model-config",
            headers=auth,
            params={"expected_version": config["version"]},
        )
        assert removed.status_code == 204, removed.text
        assert provider["requests"] == []
        result = wait_run(auth, identity).json()
        assert result["status"] == "stopped" and result["case"] is None
        assert len(result["attempts"]) == 1
        assert (
            client.post(
                f"/api/v1/training/tasks/{identity}/independent/retry", headers=auth
            ).status_code
            == 409
        )
    finally:
        stop_worker(process)


def test_stop_before_accept_keeps_late_candidate_private(tmp_path, provider, origin):
    auth, *_ = origin
    identity, _ = start_check(origin)
    process, control = start_worker(
        tmp_path, provider, identity, before_independent_accept=True
    )
    try:
        wait_until(type(control)(str(control) + ".independent_accepting").exists)
        response = client.post(f"/api/v1/training/tasks/{identity}/stop", headers=auth)
        assert response.status_code == 200 and response.json()["status"] == "stopped"
        options = json.loads(control.read_text())
        options["before_independent_accept"] = False
        control.write_text(json.dumps(options))
        wait_until(type(control)(str(control) + ".independent_finished").exists)
        result = wait_run(auth, identity).json()
        assert result["case"] is None and len(provider["requests"]) == 2
        assert all(a["total_tokens"] == 20 for a in result["attempts"])
    finally:
        options = json.loads(control.read_text())
        options["before_independent_accept"] = False
        control.write_text(json.dumps(options))
        stop_worker(process)


@pytest.mark.parametrize("publish_first", [False, True])
def test_publication_and_freeze_use_actual_shared_lock_order(
    checked, provider, monkeypatch, publish_first
):
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy import text

    from app.training import concepts, evaluations

    auth, identity, config = checked

    def unclear(context):
        result = controlled_grading(context)
        for item in result["items"]:
            item["conclusion"], item["gap"] = "unclear", "需要一次中性澄清"
        return result

    provider["grading"] = unclear
    submitted = client.post(
        f"/api/v1/training/tasks/{identity}/submissions",
        headers=auth,
        json={
            "request_id": str(uuid.uuid4()),
            "expected_config_version": config["version"],
            "disclosure_accepted": True,
            "answers": [
                {"judgment_id": "j1", "value": 0, "reason": "我按提交确认进行判断。"}
            ],
        },
    )
    assert submitted.status_code == 202, submitted.text
    wait_submission(auth, identity)
    start_evaluation(auth, identity, config)
    assert wait_evaluation(auth, identity)["status"] == "needs_clarification"
    item, _ = request_help(auth, identity, config, kind="hint")
    ready = wait_help(auth, identity, item["id"])
    root = f"/api/v1/training/tasks/{identity}/help/{item['id']}"
    confirmation = client.post(
        root + "/confirm",
        headers=auth,
        json={"content_hash": ready["content_hash"], "accepted": True},
    ).json()["id"]
    reached, release = threading.Event(), threading.Event()
    original = concepts.next_event if publish_first else evaluations.freeze

    def hold(*args):
        result = original(*args)
        reached.set()
        assert release.wait(10)
        return result

    monkeypatch.setattr(
        concepts if publish_first else evaluations,
        "next_event" if publish_first else "freeze",
        hold,
    )

    def publish():
        return client.post(
            root + "/deliver", headers=auth, json={"confirmation_id": confirmation}
        )

    def freeze():
        return client.post(
            f"/api/v1/training/tasks/{identity}/evaluation/clarification",
            headers=auth,
            json={"answers": None},
        )

    def waiting_on_owner():
        with engine.connect() as connection:
            return (
                connection.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND query LIKE '%FROM \"user\"%' AND query LIKE '%FOR UPDATE%'"
                    )
                ).scalar()
                > 0
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(publish if publish_first else freeze)
        try:
            assert reached.wait(10)
            second = pool.submit(freeze if publish_first else publish)
            wait_until(waiting_on_owner)
        finally:
            release.set()
        first_result, second_result = first.result(), second.result()
    publication = first_result if publish_first else second_result
    frozen_result = second_result if publish_first else first_result
    assert publication.status_code == 200, publication.text
    assert frozen_result.status_code == 202, frozen_result.text
    assert (
        publication.json()["exposure_sequence"]
        < frozen_result.json()["frozen_sequence"]
    ) == publish_first
    assert receipt(auth, identity, publication.json()).status_code == 200
    final = client.get(
        f"/api/v1/training/tasks/{identity}/evaluation", headers=auth
    ).json()
    assert final["independent_outcome"] == ("practice" if publish_first else "unclear")


def test_observations_and_mode_identity_are_immutable(checked):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    auth, identity, _ = checked
    evaluate(checked)
    before = client.get(
        f"/api/v1/training/tasks/{identity}/evaluation", headers=auth
    ).json()
    for statement in [
        "UPDATE training_run SET launch_mode='practice' WHERE id=:id",
        "UPDATE independent_observation SET outcome='evidenced_fail' WHERE run_id=:id",
        "DELETE FROM independent_observation WHERE run_id=:id",
    ]:
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(text(statement), {"id": uuid.UUID(identity)})
    after = client.get(
        f"/api/v1/training/tasks/{identity}/evaluation", headers=auth
    ).json()
    assert (
        after["independent_outcome"]
        == before["independent_outcome"]
        == "independent_pass_candidate"
    )
    assert (
        after["inputs"] == before["inputs"]
        and after["frozen_sequence"] == before["frozen_sequence"]
    )


def test_failed_job_reconcile_cannot_overwrite_a_new_retry(
    origin, provider, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor

    import procrastinate

    from app.training import worker
    from app.training.queue import DSN

    auth, *_ = origin
    identity, _ = start_check(origin)
    with Session(engine) as session:
        old_job = session.get(TrainingRun, uuid.UUID(identity)).queue_job_id
    with procrastinate.App(
        connector=procrastinate.SyncPsycopgConnector(conninfo=DSN)
    ).open() as app:
        app.job_manager.cancel_job_by_id(old_job, abort=True)
    selected, release = threading.Event(), threading.Event()
    original_finish = worker.finish

    def delayed_finish(run_id, code, message, job_id=None):
        if str(run_id) == identity:
            selected.set()
            assert release.wait(10)
        return original_finish(run_id, code, message, job_id)

    monkeypatch.setattr(worker, "finish", delayed_finish)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(worker.reconcile_stops)
        try:
            assert selected.wait(10), "old cancelled job was not selected"
            stopped = client.post(
                f"/api/v1/training/tasks/{identity}/stop", headers=auth
            )
            assert stopped.status_code == 200 and stopped.json()["status"] == "stopped"
            retry = client.post(
                f"/api/v1/training/tasks/{identity}/independent/retry", headers=auth
            )
            assert retry.status_code == 202, retry.text
            before = client.get(
                f"/api/v1/training/tasks/{identity}", headers=auth
            ).json()
            with Session(engine) as session:
                new_job = session.get(TrainingRun, uuid.UUID(identity)).queue_job_id
            assert new_job != old_job and before["status"] == "queued"
        finally:
            release.set()
        pending.result(timeout=10)
    after = client.get(f"/api/v1/training/tasks/{identity}", headers=auth).json()
    try:
        assert after == before
        assert len(provider["requests"]) == 0
    finally:
        assert (
            client.post(
                f"/api/v1/training/tasks/{identity}/stop", headers=auth
            ).status_code
            == 200
        )


def test_old_execution_waiting_for_credential_cannot_claim_retry_budget(
    tmp_path, provider, origin
):
    auth, *_ = origin
    identity, _ = start_check(origin)
    process, control = start_worker(
        tmp_path,
        provider,
        identity,
        independent_once=True,
        before_independent_credential=True,
    )
    try:
        wait_until(type(control)(str(control) + ".credential_waiting").exists)
        with Session(engine) as session:
            old_job = session.get(TrainingRun, uuid.UUID(identity)).queue_job_id
        stopped = client.post(f"/api/v1/training/tasks/{identity}/stop", headers=auth)
        assert stopped.status_code == 200 and stopped.json()["status"] == "stopped"
        retry = client.post(
            f"/api/v1/training/tasks/{identity}/independent/retry", headers=auth
        )
        assert retry.status_code == 202, retry.text
        before = client.get(f"/api/v1/training/tasks/{identity}", headers=auth).json()
        with Session(engine) as session:
            run = session.get(TrainingRun, uuid.UUID(identity))
            assert run.queue_job_id != old_job
            assert (run.attempts, run.generation_attempts) == (0, 0)
        options = json.loads(control.read_text())
        options["before_independent_credential"] = False
        control.write_text(json.dumps(options))
        wait_until(type(control)(str(control) + ".execution_finished").exists)
        assert process.wait(timeout=3) == 0
        after = client.get(f"/api/v1/training/tasks/{identity}", headers=auth).json()
        assert after == before
        assert provider["requests"] == []
        with Session(engine) as session:
            run = session.get(TrainingRun, uuid.UUID(identity))
            assert (run.attempts, run.generation_attempts) == (0, 0)
        # A fresh queue worker can still finish the retry with its full budget.
        process, _ = start_worker(tmp_path, provider, identity)
        result = wait_run(auth, identity).json()
        assert result["status"] == "completed", result
        assert len(result["attempts"]) == len(provider["requests"]) == 2
    finally:
        stop_worker(process)
        client.post(f"/api/v1/training/tasks/{identity}/stop", headers=auth)
