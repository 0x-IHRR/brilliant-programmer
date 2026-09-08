"""Real API, PostgreSQL, independent worker and controlled TLS grading witnesses."""

import copy
import json
import time
import uuid

import pytest
from sqlmodel import Session

from app.core.db import engine
from app.training.evaluation_models import Evaluation
from app.training.events import next_event
from app.training.models import TrainingRun
from tests.test_accounts import client
from tests.test_model_config import FAKE_KEY, account
from tests.test_submissions import wait_submission
from tests.test_training import provider as training_provider
from tests.test_training import start_run, start_worker, stop_worker, wait_run

provider = training_provider


def grading(context, verdict="pass"):
    task = context["task"]
    items = []
    for judgment in task["judgments"]:
        rubric = next(r for r in task["rubric"] if r["judgment_id"] == judgment["id"])
        original = next(
            a
            for a in context["inputs"]["original"]
            if a["judgment_id"] == judgment["id"]
        )
        clarification = context["inputs"]["clarification"]
        answer = (
            next(a for a in clarification if a["judgment_id"] == judgment["id"])
            if clarification
            else original
        )
        material = task["evidence"][0]
        quotes = [{"input": "original", "field": "reason", "quote": original["reason"]}]
        if clarification:
            quotes.append(
                {"input": "clarification", "field": "reason", "quote": answer["reason"]}
            )
        items.append(
            {
                "judgment_id": judgment["id"],
                "conclusion": verdict,
                "answer_quotes": quotes,
                "grounding": [
                    {
                        "evidence_id": material["id"],
                        "fact": "confirmed",
                        "value": "false",
                        "citation": material["citations"][0],
                    }
                ],
                "interpreted_value": answer["value"],
                "interpreted_reasoning": answer["value"],
                "reason_claims": [
                    {
                        "answer_quote": len(quotes) - 1,
                        "grounding": 0,
                        "interpreted_fact_value": "false",
                    }
                ],
                "rule_quote": rubric["reasoning"],
                "counterexample_quote": rubric["counterexample"]
                if verdict == "evidenced_fail"
                else None,
                "explanation": "当前确认记录与原答推理对照；这是受控供应商候选。",
                "gap": None if verdict == "pass" else "原答不能确定执行状态",
            }
        )
    return {"items": items}


@pytest.fixture
def ready(tmp_path, provider, request):
    provider["grading"] = grading
    owner, auth, run_id = start_run(provider)
    process, control = start_worker(tmp_path, provider, run_id)
    try:
        assert wait_run(auth, run_id).json()["status"] == "completed"
        config = client.get("/api/v1/model-config", headers=auth).json()
        answer = {
            "judgment_id": "j1",
            "value": getattr(request, "param", 0),
            "reason": "确认可能丢失，因此尚不能断定请求未执行。",
        }
        response = client.post(
            f"/api/v1/training/tasks/{run_id}/submissions",
            headers=auth,
            json={
                "request_id": str(uuid.uuid4()),
                "answers": [answer],
                "expected_config_version": config["version"],
                "disclosure_accepted": True,
            },
        )
        assert response.status_code == 202, response.text
        assert wait_submission(auth, run_id)["awarded_points"] == 10
        yield auth, run_id, config, answer, process, control
    finally:
        stop_worker(process)


def endpoint(run_id):
    return f"/api/v1/training/tasks/{run_id}/evaluation"


def start(auth, run_id, config):
    response = client.post(
        endpoint(run_id),
        headers=auth,
        json={
            "disclosure_accepted": True,
            "expected_config_version": config["version"],
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def wait(auth, run_id):
    until = time.monotonic() + 15
    while time.monotonic() < until:
        response = client.get(endpoint(run_id), headers=auth)
        assert response.status_code == 200, response.text
        if response.json()["status"] not in {"checking", "stopping"}:
            return response.json()
        time.sleep(0.04)
    raise AssertionError(response.text)


def test_pass_freezes_once_without_reward_or_hidden_extra_fields(ready, provider):
    auth, identity, config, *_ = ready
    start(auth, identity, config)
    result = wait(auth, identity)
    assert result["status"] == "completed", result
    assert result["frozen_sequence"] and result["frozen_at"]
    assert result["result"]["items"][0]["conclusion"] == "pass"
    assert result["result"]["items"][0]["gap"] is None
    context = json.loads(provider["requests"][-1]["messages"][1]["content"])
    assert set(context) == {
        "purpose",
        "task",
        "sources",
        "inputs",
        "rule_version",
        "schema",
    }
    assert "HIDDEN_HELP" not in json.dumps(context) and FAKE_KEY not in json.dumps(
        context
    )
    assert start(auth, identity, config)["frozen_sequence"] == result["frozen_sequence"]
    assert len(provider["requests"]) == 3
    with Session(engine) as session:
        item = session.get(Evaluation, uuid.UUID(identity))
        assert next_event(session, item.run_id) > item.frozen_sequence
        session.rollback()
        item.inputs = {}
        session.add(item)
        with pytest.raises(Exception, match="immutable evaluation input"):
            session.commit()
    assert wait_submission(auth, identity)["awarded_points"] == 10
    _, stranger = account()
    assert client.get(endpoint(identity), headers=stranger).status_code == 404


@pytest.mark.parametrize("end", [False, True])
def test_one_neutral_clarification_then_freeze(ready, provider, end):
    auth, identity, config, answer, *_ = ready
    provider["grading"] = lambda context: grading(
        context, "unclear" if not context["inputs"]["clarification"] else "pass"
    )
    start(auth, identity, config)
    result = wait(auth, identity)
    assert result["status"] == "needs_clarification", result
    assert result["frozen_sequence"] is None and result["result"] is None
    assert "HIDDEN_" not in json.dumps(result)
    body = {
        "answers": None
        if end
        else [{**answer, "reason": "我指的是请求可能已执行，仅确认缺失。"}]
    }
    response = client.post(
        endpoint(identity) + "/clarification", headers=auth, json=body
    )
    assert response.status_code == 202, response.text
    assert response.json()["frozen_sequence"]
    result = wait(auth, identity)
    assert result["status"] == "completed", result
    assert result["result"]["items"][0]["conclusion"] == ("unclear" if end else "pass")
    assert result["inputs"]["original"]["answers"] == [answer]
    assert (
        client.post(
            endpoint(identity) + "/clarification",
            headers=auth,
            json={"answers": [answer]},
        ).json()["inputs"]
        == result["inputs"]
    )
    assert len(provider["requests"]) == (3 if end else 4)


@pytest.mark.parametrize(
    "mode,code,attempts",
    [("auth", "authentication", 1), ("limited", "rate_limited", 3)],
)
def test_system_failure_keeps_award(ready, provider, mode, code, attempts):
    auth, identity, config, *_ = ready
    provider["mode"] = mode
    start(auth, identity, config)
    result = wait(auth, identity)
    assert result["status"] == "failed", result
    assert result["code"] == code and len(result["attempts"]) == attempts
    assert result["result"] is None
    assert wait_submission(auth, identity)["awarded_points"] == 10


def test_invalid_case_never_calls_grading(ready, provider):
    auth, identity, config, *_ = ready
    with Session(engine) as session:
        run = session.get(TrainingRun, uuid.UUID(identity))
        case = copy.deepcopy(run.candidate)
        case["missing_evidence"] = ["必要事实缺失"]
        run.candidate = case
        session.add(run)
        session.commit()
    start(auth, identity, config)
    result = wait(auth, identity)
    assert result["code"] == "invalid_case", result
    assert result["attempts"] == [] and len(provider["requests"]) == 2
    assert wait_submission(auth, identity)["awarded_points"] == 10


@pytest.mark.parametrize(
    "ready,verdict,multiple",
    [(1, "evidenced_fail", False), (1, "pass", True)],
    indirect=["ready"],
)
def test_wrong_and_alternative_valid_decision(ready, provider, verdict, multiple):
    auth, identity, config, *_ = ready
    if multiple:
        with Session(engine) as session:
            run = session.get(TrainingRun, uuid.UUID(identity))
            case = copy.deepcopy(run.candidate)
            case["rubric"][0]["acceptable_options"] = [0, 1]
            run.candidate = case
            session.add(run)
            session.commit()
    provider["grading"] = lambda context: grading(context, verdict)
    start(auth, identity, config)
    result = wait(auth, identity)
    assert result["status"] == "completed", result
    assert result["result"]["items"][0]["conclusion"] == verdict
    assert wait_submission(auth, identity)["awarded_points"] == 10


def test_prior_neutral_opportunity_cannot_ask_again(ready, provider):
    from sqlmodel import select

    from app.training.submission_models import Submission

    auth, identity, config, *_ = ready
    with Session(engine) as session:
        original = session.exec(
            select(Submission).where(Submission.run_id == uuid.UUID(identity))
        ).one()
        original.neutral_clarification = True
        session.add(original)
        session.commit()
    provider["grading"] = lambda context: grading(context, "unclear")
    accepted = start(auth, identity, config)
    assert accepted["frozen_sequence"]
    result = wait(auth, identity)
    assert result["status"] == "completed", result
    assert result["result"]["items"][0]["conclusion"] == "unclear"
    assert len(provider["requests"]) == 3


def test_invalid_grading_is_system_failure_not_ability_failure(ready, provider):
    auth, identity, config, *_ = ready

    def forged(context):
        result = grading(context)
        result["items"][0]["grounding"][0]["citation"]["quote"] = "invented quotation"
        return result

    provider["grading"] = forged
    start(auth, identity, config)
    result = wait(auth, identity)
    assert result["code"] == "invalid_response" and result["result"] is None
    assert len(result["attempts"]) == 1 and result["attempts"][0]["total_tokens"] == 20
    assert wait_submission(auth, identity)["awarded_points"] == 10


def test_stop_before_http_then_explicit_resume(ready, provider):
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    auth, identity, config, _, _, control = ready
    options = json.loads(control.read_text())
    options["before_http"] = True
    control.write_text(json.dumps(options))
    start(auth, identity, config)
    deadline = time.monotonic() + 10
    while not Path(str(control) + ".blocked").exists():
        assert time.monotonic() < deadline
        time.sleep(0.02)
    with ThreadPoolExecutor() as executor:
        stopped = executor.submit(
            client.post, endpoint(identity) + "/stop", headers=auth
        )
        response = stopped.result(5)
    assert response.status_code == 200 and response.json()["status"] == "stopped"
    assert len(provider["requests"]) == 2
    options["before_http"] = False
    control.write_text(json.dumps(options))
    assert client.post(endpoint(identity) + "/retry", headers=auth).status_code == 202
    result = wait(auth, identity)
    assert result["status"] == "completed", result
    assert len(result["attempts"]) == 2 and len(provider["requests"]) == 3


def test_crashed_worker_keeps_budget_and_job(ready, provider, tmp_path):
    auth, identity, config, _, process, _ = ready
    provider["mode"] = "hold"
    provider["received"].clear()
    start(auth, identity, config)
    assert provider["received"].wait(5)
    with Session(engine) as session:
        before = session.get(Evaluation, uuid.UUID(identity)).queue_job_id
    process.kill()
    process.wait(5)
    provider["mode"] = "ok"
    provider["release"].set()
    time.sleep(0.7)
    recovered, _ = start_worker(tmp_path, provider, identity)
    try:
        result = wait(auth, identity)
        assert result["status"] == "completed", result
        assert (
            len(result["attempts"]) == 2 and result["attempts"][0]["code"] == "unknown"
        )
        with Session(engine) as session:
            assert session.get(Evaluation, uuid.UUID(identity)).queue_job_id == before
    finally:
        stop_worker(recovered)


def test_retry_six_attempt_cap_and_configuration_revoke(ready, provider):
    auth, identity, config, *_ = ready
    provider["mode"] = "limited"
    start(auth, identity, config)
    assert len(wait(auth, identity)["attempts"]) == 3
    assert client.post(endpoint(identity) + "/retry", headers=auth).status_code == 202
    result = wait(auth, identity)
    assert len(result["attempts"]) == 6 and not result["can_retry"]
    assert client.post(endpoint(identity) + "/retry", headers=auth).status_code == 409
    assert len(provider["requests"]) == 8
    assert wait_submission(auth, identity)["awarded_points"] == 10


def test_revoked_configuration_cannot_resume_old_evaluation(ready, provider):
    auth, identity, config, *_ = ready
    provider["mode"] = "limited"
    start(auth, identity, config)
    assert wait(auth, identity)["status"] == "failed"
    assert (
        client.delete(
            "/api/v1/model-config",
            headers=auth,
            params={"expected_version": config["version"]},
        ).status_code
        == 204
    )
    assert client.post(endpoint(identity) + "/retry", headers=auth).status_code == 409
    assert len(provider["requests"]) == 5


def test_correct_decision_with_factually_wrong_reason_fails(ready, provider):
    auth, identity, config, *_ = ready

    def wrong_reason(context):
        result = grading(context, "evidenced_fail")
        result["items"][0]["reason_claims"][0]["interpreted_fact_value"] = "true"
        return result

    provider["grading"] = wrong_reason
    start(auth, identity, config)
    result = wait(auth, identity)
    assert result["status"] == "completed", result
    assert result["result"]["items"][0]["conclusion"] == "evidenced_fail"


def test_end_clarification_without_model_configuration(ready, provider):
    auth, identity, config, *_ = ready
    provider["grading"] = lambda context: grading(context, "unclear")
    start(auth, identity, config)
    assert wait(auth, identity)["status"] == "needs_clarification"
    deleted = client.delete(
        "/api/v1/model-config",
        headers=auth,
        params={"expected_version": config["version"]},
    )
    assert deleted.status_code == 204
    response = client.post(
        endpoint(identity) + "/clarification", headers=auth, json={"answers": None}
    )
    assert response.status_code == 202, response.text
    result = response.json()
    assert result["status"] == "completed" and result["frozen_sequence"]
    assert result["result"]["items"][0]["conclusion"] == "unclear"
    assert len(provider["requests"]) == 3


def test_post_freeze_review_appends_without_model_or_award(ready, provider):
    from sqlmodel import select

    from app.training.submission_models import PracticeAward, Submission

    auth, identity, config, answer, *_ = ready
    start(auth, identity, config)
    frozen = wait(auth, identity)
    submissions = client.get(
        f"/api/v1/training/tasks/{identity}/submissions", headers=auth
    ).json()
    original = submissions["submissions"][0]
    response = client.post(
        f"/api/v1/training/tasks/{identity}/submissions",
        headers=auth,
        json={
            "request_id": str(uuid.uuid4()),
            "previous_submission_id": original["id"],
            "expected_config_version": config["version"],
            "disclosure_accepted": True,
            "answers": [{**answer, "value": 1, "reason": "这是冻结后的复盘改答"}],
        },
    )
    assert response.status_code == 202, response.text
    saved = response.json()["submissions"][-1]
    assert saved["kind"] == "supplement" and saved["original_id"] == original["id"]
    assert saved["sequence"] > frozen["frozen_sequence"] > original["sequence"]
    assert saved["code"] == "review_saved" and saved["attempts"] == []
    after = client.get(endpoint(identity), headers=auth).json()
    assert after["inputs"] == frozen["inputs"] and after["result"] == frozen["result"]
    assert len(provider["requests"]) == 3
    with Session(engine) as session:
        assert (
            len(
                session.exec(
                    select(PracticeAward).where(
                        PracticeAward.run_id == uuid.UUID(identity)
                    )
                ).all()
            )
            == 1
        )
        assert session.get(Submission, uuid.UUID(saved["id"])).queue_job_id is None
        assert session.get(Submission, uuid.UUID(original["id"])).answers == [answer]


@pytest.mark.parametrize("response_format", ["json", "sse"])
def test_encoded_model_key_never_reaches_result_or_public_api(
    ready, provider, response_format
):
    auth, identity, config, *_ = ready

    def leaked(context):
        result = grading(context)
        result["items"][0]["explanation"] = FAKE_KEY
        return result

    provider["grading"] = leaked
    provider["escaped_output"] = True
    provider["response_format"] = response_format
    start(auth, identity, config)
    result = wait(auth, identity)
    assert result["code"] == "invalid_response" and result["result"] is None
    assert FAKE_KEY not in json.dumps(result)
    assert result["attempts"][0]["total_tokens"] == 20
    with Session(engine) as session:
        assert session.get(Evaluation, uuid.UUID(identity)).result is None


@pytest.mark.parametrize("recovery", ["repeat_stop", "background"])
def test_interrupted_stopping_can_finish_and_retry(
    ready, provider, monkeypatch, tmp_path, recovery
):
    import procrastinate

    from app.training.evaluation_worker import reconcile_failed_evaluations

    auth, identity, config, _, process, _ = ready
    stop_worker(process)
    start(auth, identity, config)
    original_open = procrastinate.App.open

    def broken_open(*_args, **_kwargs):
        raise RuntimeError("controlled queue connection failure")

    monkeypatch.setattr(procrastinate.App, "open", broken_open)
    with pytest.raises(RuntimeError, match="controlled queue connection failure"):
        client.post(endpoint(identity) + "/stop", headers=auth)
    assert client.get(endpoint(identity), headers=auth).json()["status"] == "stopping"
    monkeypatch.setattr(procrastinate.App, "open", original_open)
    if recovery == "repeat_stop":
        assert (
            client.post(endpoint(identity) + "/stop", headers=auth).json()["status"]
            == "stopped"
        )
    else:
        reconcile_failed_evaluations()
        assert (
            client.get(endpoint(identity), headers=auth).json()["status"] == "stopped"
        )
    assert len(provider["requests"]) == 2
    assert client.post(endpoint(identity) + "/retry", headers=auth).status_code == 202
    resumed, _ = start_worker(tmp_path, provider, identity)
    try:
        assert wait(auth, identity)["status"] == "completed"
        assert len(provider["requests"]) == 3
    finally:
        stop_worker(resumed)


def test_older_stop_cannot_cancel_or_overwrite_retried_job(
    ready, provider, monkeypatch, tmp_path
):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    import procrastinate

    from app.training.queue import DSN

    auth, identity, config, _, process, _ = ready
    stop_worker(process)
    start(auth, identity, config)
    with Session(engine) as session:
        previous_job = session.get(Evaluation, uuid.UUID(identity)).queue_job_id
    manager_type = type(
        procrastinate.App(
            connector=procrastinate.SyncPsycopgConnector(conninfo=DSN)
        ).job_manager
    )
    original_cancel = manager_type.cancel_job_by_id
    entered, release = threading.Event(), threading.Event()

    def paused_cancel(manager, job_id, *args, **kwargs):
        if not entered.is_set():
            entered.set()
            assert release.wait(10)
        return original_cancel(manager, job_id, *args, **kwargs)

    monkeypatch.setattr(manager_type, "cancel_job_by_id", paused_cancel)
    with ThreadPoolExecutor() as executor:
        late_stop = executor.submit(
            client.post, endpoint(identity) + "/stop", headers=auth
        )
        assert entered.wait(5)
        try:
            assert (
                client.post(endpoint(identity) + "/stop", headers=auth).json()["status"]
                == "stopped"
            )
            assert (
                client.post(endpoint(identity) + "/retry", headers=auth).status_code
                == 202
            )
            with Session(engine) as session:
                new_job = session.get(Evaluation, uuid.UUID(identity)).queue_job_id
            assert new_job != previous_job
        finally:
            release.set()
        assert late_stop.result(5).json()["status"] == "checking"
    assert len(provider["requests"]) == 2
    resumed, _ = start_worker(tmp_path, provider, identity)
    try:
        assert wait(auth, identity)["status"] == "completed"
        assert len(provider["requests"]) == 3
    finally:
        stop_worker(resumed)
