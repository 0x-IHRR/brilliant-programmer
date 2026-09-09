"""Guided practice through the actual API, PostgreSQL, worker and controlled TLS."""

import json
import time
import uuid

import pytest
from sqlmodel import Session, select

from app.core.db import engine
from app.training.submission_models import PracticeAward, Submission
from tests.test_accounts import client
from tests.test_concepts import coach, publish, receipt, request, wait
from tests.test_model_config import account
from tests.test_training import (
    candidate,
    start_run,
    start_worker,
    stop_worker,
    wait_run,
)
from tests.test_training import provider as training_provider

provider = training_provider


def guided_coach(context):
    if context["purpose"] == "concept_generate":
        return coach(context)
    return {
        "sections": [
            {
                "section": name,
                "quote": text,
                "direction": "neutral",
                "reason": "受控检查，文本与冻结材料相符。",
                "accuracy": "supported",
                "unsafe": False,
                "claims_understanding": False,
            }
            for name, text in context["content_sections"].items()
        ]
    }


def safe_case(payload):
    value = candidate(payload)
    value["evidence"][0]["text"] = "请求尚未收到确认，需要查看实际处理证据。"
    return value


@pytest.fixture
def ready(tmp_path, provider):
    provider["candidate"] = safe_case
    provider["coach"] = guided_coach
    provider["all_kinds"] = True
    _, auth, identity = start_run(provider)
    process, control = start_worker(tmp_path, provider, identity)
    try:
        assert wait_run(auth, identity).json()["status"] == "completed"
        config = client.get("/api/v1/model-config", headers=auth).json()
        yield auth, identity, config, process, control
    finally:
        stop_worker(process)


def demo(ready):
    auth, identity, config, *_ = ready
    item, _ = request(auth, identity, config, kind="demonstration")
    result = wait(auth, identity, item["id"])
    assert result["status"] == "ready", result
    assert (
        result["direction"] == "directional"
    )  # Inspector cannot relabel a solution neutral.
    return item["id"]


def url(identity, help_id):
    return f"/api/v1/training/tasks/{identity}/help/{help_id}/practice"


def wait_practice(auth, path):
    deadline = time.monotonic() + 15
    while True:
        result = client.get(path, headers=auth).json()
        submissions = result["records"]["submissions"]
        if submissions and submissions[-1]["status"] not in {"checking", "stopping"}:
            return result
        assert time.monotonic() < deadline, result
        time.sleep(0.03)


def body(config, **extra):
    return {
        "request_id": str(uuid.uuid4()),
        "expected_config_version": config["version"],
        "disclosure_accepted": True,
        "answers": [
            {
                "judgment_id": "j1",
                "value": 1,
                "reason": "我想先查看处理记录，不知道原因。",
            }
        ],
        **extra,
    }


def test_guidance_private_until_delivery_and_one_check_without_generation(
    ready, provider
):
    auth, identity, config, *_ = ready
    help_id = demo(ready)
    assert len(provider["requests"]) == 2
    metadata = client.get(
        f"/api/v1/training/tasks/{identity}/help", headers=auth
    ).json()
    assert "steps" not in json.dumps(metadata)
    assert client.get(url(identity, help_id), headers=auth).status_code == 409
    published = publish(auth, identity, help_id)
    assert published["content"]["kind"] == "demonstration"
    assert published["content"]["steps"][0]["solution"]["reasoning"]
    assert client.get(url(identity, help_id), headers=auth).status_code == 409
    assert receipt(auth, identity, published).status_code == 200
    exercise = client.get(url(identity, help_id), headers=auth).json()
    assert len(exercise["exercise"]["case"]["judgments"]) == 1
    assert exercise["exercise"]["kind"] == "same_scenario_practice"
    assert "rubric" not in json.dumps(
        exercise
    ) and "acceptable_values" not in json.dumps(exercise)
    assert exercise["records"]["awarded_points"] == 0
    _, stranger = account()
    assert client.get(url(identity, help_id), headers=stranger).status_code == 404


def test_practice_first_award_does_not_complete_original_or_pay_twice(ready, provider):
    auth, identity, config, *_ = ready
    help_id = demo(ready)
    receipt(auth, identity, publish(auth, identity, help_id))
    path = url(identity, help_id)
    submitted = body(config)
    assert client.post(path, headers=auth, json=submitted).status_code == 202
    result = wait_practice(auth, path)
    assert result["completed"] and result["records"]["awarded_points"] == 10
    count = len(provider["requests"])
    assert client.post(path, headers=auth, json=submitted).status_code == 202
    original_path = f"/api/v1/training/tasks/{identity}/submissions"
    original = client.get(original_path, headers=auth).json()
    assert original["completed_at"] is None and original["submissions"] == []
    assert original["awarded_points"] == 10
    case = client.get(f"/api/v1/training/tasks/{identity}", headers=auth).json()["case"]
    original_body = body(config)
    original_body["answers"] = [
        {
            "judgment_id": j["id"],
            "value": [0, 1, 2]
            if j["kind"] == "order"
            else "需要查证"
            if j["kind"] == "prediction"
            else 1,
            "reason": "需要查看实际处理记录",
        }
        for j in case["judgments"]
    ]
    assert (
        client.post(original_path, headers=auth, json=original_body).status_code == 202
    )
    deadline = time.monotonic() + 10
    while not (original := client.get(original_path, headers=auth).json())[
        "completed_at"
    ]:
        assert time.monotonic() < deadline
        time.sleep(0.03)
    assert len(original["submissions"]) == 1 and original["awarded_points"] == 10
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
        assert (
            len(
                session.exec(
                    select(Submission).where(Submission.run_id == uuid.UUID(identity))
                ).all()
            )
            == 2
        )
    assert len(provider["requests"]) == count + 1


def test_practice_draft_is_separate_and_original_lineage_unchanged(ready, provider):
    auth, identity, config, *_ = ready
    original_path = f"/api/v1/training/tasks/{identity}/draft"
    original = {
        "request_id": str(uuid.uuid4()),
        "expected_version": None,
        "progress": {
            "answers": [{"judgment_id": "j2", "value": [2], "reason": "原题未完"}],
            "step": "materials",
        },
    }
    stored = client.put(original_path, headers=auth, json=original)
    assert stored.status_code == 200
    help_id = demo(ready)
    receipt(auth, identity, publish(auth, identity, help_id))
    path = url(identity, help_id)
    before = len(provider["requests"])
    draft = {
        "request_id": str(uuid.uuid4()),
        "expected_version": None,
        "progress": {
            "answers": [{"judgment_id": "j1", "value": None, "reason": "跟练也未完"}],
            "step": "judgments",
        },
    }
    saved = client.put(path + "/draft", headers=auth, json=draft)
    assert saved.status_code == 200, saved.text
    assert client.get(original_path, headers=auth).json() == stored.json()
    assert client.get(path + "/draft", headers=auth).json() == saved.json()
    assert client.put(path + "/draft", headers=auth, json=draft).json() == saved.json()
    other = {**draft, "request_id": str(uuid.uuid4())}
    assert client.put(path + "/draft", headers=auth, json=other).status_code == 409
    assert len(provider["requests"]) == before
    assert not client.get(path, headers=auth).json()["completed"]
    assert client.get(path, headers=auth).json()["records"]["awarded_points"] == 0

    second_help = demo(ready)
    receipt(auth, identity, publish(auth, identity, second_help))
    second_path = url(identity, second_help)
    before = len(provider["requests"])
    assert client.get(second_path + "/draft", headers=auth).json() is None
    second_draft = {
        **draft,
        "request_id": str(uuid.uuid4()),
        "progress": {
            "answers": [{"judgment_id": "j1", "value": 0, "reason": "另一份练习输入"}],
            "step": "coach",
        },
    }
    second_saved = client.put(second_path + "/draft", headers=auth, json=second_draft)
    assert second_saved.status_code == 200, second_saved.text
    assert client.get(path + "/draft", headers=auth).json() == saved.json()
    assert client.get(second_path + "/draft", headers=auth).json() == second_saved.json()
    assert client.get(original_path, headers=auth).json() == stored.json()
    assert len(provider["requests"]) == before


def test_hint_never_returns_solution_and_only_demo_unlocks_practice(ready):
    auth, identity, config, *_ = ready
    hint, _ = request(auth, identity, config, kind="hint")
    assert wait(auth, identity, hint["id"])["status"] == "ready"
    publication = publish(auth, identity, hint["id"])
    assert all(s["solution"] is None for s in publication["content"]["steps"])
    assert not any("-answer-" in name for name in publication["sections"])
    receipt(auth, identity, publication)
    assert client.get(url(identity, hint["id"]), headers=auth).status_code == 409


def test_safe_saved_demo_read_after_key_delete_and_no_new_call(ready, provider):
    auth, identity, config, *_ = ready
    help_id = demo(ready)
    assert (
        client.delete(
            "/api/v1/model-config",
            headers=auth,
            params={"expected_version": config["version"]},
        ).status_code
        == 204
    )
    published = publish(auth, identity, help_id)
    assert receipt(auth, identity, published).status_code == 200
    assert client.get(url(identity, help_id), headers=auth).status_code == 200
    assert (
        client.post(url(identity, help_id), headers=auth, json=body(config)).status_code
        == 409
    )
    assert len(provider["requests"]) == 2


@pytest.mark.parametrize("fault", ["secret", "unsafe", "unbound"])
def test_inspection_failure_keeps_guidance_private(ready, provider, fault):
    from tests.test_model_config import FAKE_KEY

    auth, identity, config, *_ = ready

    def inspect(context):
        result = guided_coach(context)
        if fault == "secret":
            result["sections"][0]["reason"] = FAKE_KEY
        if fault == "unsafe":
            result["sections"][0]["unsafe"] = True
        if fault == "unbound":
            result["sections"][0]["quote"] = "not the same frozen content"
        return result

    provider["coach"] = inspect
    item, _ = request(auth, identity, config, kind="demonstration")
    result = wait(auth, identity, item["id"])
    assert result["status"] == "failed", result
    assert not result["deliveries"]
    assert (
        client.post(
            f"/api/v1/training/tasks/{identity}/help/{item['id']}/deliver", headers=auth
        ).status_code
        == 409
    )
    assert "steps" not in json.dumps(result) and FAKE_KEY not in json.dumps(result)
    assert result["attempts"][0]["prompt_tokens"] is not None


def test_practice_partial_unrelated_and_repeat_review_never_add_award(ready, provider):
    auth, identity, config, *_ = ready
    help_id = demo(ready)
    receipt(auth, identity, publish(auth, identity, help_id))
    path = url(identity, help_id)
    for answers in [[], [{"judgment_id": "j1", "value": 1, "reason": " "}]]:
        assert (
            client.post(
                path, headers=auth, json=body(config, answers=answers)
            ).status_code
            == 422
        )
    provider["relevance"] = "unclear"
    assert client.post(path, headers=auth, json=body(config)).status_code == 202
    pending = wait_practice(auth, path)
    assert not pending["completed"] and pending["records"]["awarded_points"] == 0
    assert pending["records"]["submissions"][-1]["neutral_clarification"]
    provider["relevance"] = "related"
    answer = body(
        config, previous_submission_id=pending["records"]["submissions"][-1]["id"]
    )
    answer["answers"][0]["reason"] = "因为需要确认请求实际执行过没有。"
    assert client.post(path, headers=auth, json=answer).status_code == 202
    completed = wait_practice(auth, path)
    assert completed["completed"] and completed["records"]["awarded_points"] == 10
    calls = len(provider["requests"])
    review = body(
        config, previous_submission_id=completed["records"]["submissions"][-1]["id"]
    )
    review["answers"][0]["reason"] = "复盘：下次先核对处理记录。"
    saved = client.post(path, headers=auth, json=review)
    assert (
        saved.status_code == 202
        and saved.json()["records"]["submissions"][-1]["code"] == "review_saved"
    )
    assert (
        saved.json()["records"]["awarded_points"] == 10
        and len(provider["requests"]) == calls
    )


def queued_submission(ready, practice):
    auth, identity, config, process, _ = ready
    help_id = None
    if practice:
        help_id = demo(ready)
        receipt(auth, identity, publish(auth, identity, help_id))
    stop_worker(process)
    path = (
        url(identity, help_id)
        if practice
        else f"/api/v1/training/tasks/{identity}/submissions"
    )
    value = body(config)
    if not practice:
        case = client.get(f"/api/v1/training/tasks/{identity}", headers=auth).json()[
            "case"
        ]
        value["answers"] = [
            {
                "judgment_id": j["id"],
                "value": [0, 1, 2]
                if j["kind"] == "order"
                else "待核对"
                if j["kind"] == "prediction"
                else 1,
                "reason": "想查看处理记录",
            }
            for j in case["judgments"]
        ]
    response = client.post(path, headers=auth, json=value)
    assert response.status_code == 202, response.text
    return path, value["request_id"]


@pytest.mark.parametrize("practice", [False, True])
@pytest.mark.parametrize("fault", ["open", "cancel"])
def test_interrupted_stop_recovers_same_job_and_keeps_input(
    ready, monkeypatch, practice, fault
):
    from app.training import submission_worker

    auth, identity, *_ = ready
    path, submission_id = queued_submission(ready, practice)
    with Session(engine) as session:
        old_job = session.get(Submission, uuid.UUID(submission_id)).queue_job_id
    target = (
        submission_worker.procrastinate.App
        if fault == "open"
        else type(submission_worker.queue.job_manager)
    )
    method = "open" if fault == "open" else "cancel_job_by_id"
    real_open = getattr(target, method)

    def fail_open(*_args, **_kwargs):
        raise RuntimeError("controlled queue unavailable")

    monkeypatch.setattr(target, method, fail_open)
    with pytest.raises(RuntimeError, match="controlled queue"):
        client.post(path + f"/{submission_id}/stop", headers=auth)
    with Session(engine) as session:
        assert session.get(Submission, uuid.UUID(submission_id)).status == "stopping"
    monkeypatch.setattr(target, method, real_open)
    submission_worker.reconcile_failed_submissions()
    assert client.post(path + f"/{submission_id}/stop", headers=auth).status_code == 200
    assert (
        client.post(path + f"/{submission_id}/retry", headers=auth).status_code == 202
    )
    with Session(engine) as session:
        item = session.get(Submission, uuid.UUID(submission_id))
        assert (
            item.status == "checking"
            and not item.stop_requested
            and item.queue_job_id != old_job
        )

    assert client.post(path + f"/{submission_id}/stop", headers=auth).status_code == 200


@pytest.mark.parametrize("practice", [False, True])
def test_old_stop_cannot_cancel_or_replace_new_retry(ready, monkeypatch, practice):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from app.training import submissions

    auth, identity, *_ = ready
    path, submission_id = queued_submission(ready, practice)
    entered, release = Event(), Event()
    original_finish = submissions.finish_submission_stop
    jobs = []

    def held_finish(identity, job_id):
        jobs.append(job_id)
        if len(jobs) == 1:
            entered.set()
            assert release.wait(8)
        original_finish(identity, job_id)

    monkeypatch.setattr(submissions, "finish_submission_stop", held_finish)
    with ThreadPoolExecutor(1) as pool:
        old = pool.submit(client.post, path + f"/{submission_id}/stop", headers=auth)
        try:
            assert entered.wait(5)
            assert (
                client.post(path + f"/{submission_id}/stop", headers=auth).status_code
                == 200
            )
            assert (
                client.post(path + f"/{submission_id}/retry", headers=auth).status_code
                == 202
            )
            with Session(engine) as session:
                new_job = session.get(Submission, uuid.UUID(submission_id)).queue_job_id
        finally:
            release.set()
        assert old.result(5).status_code == 200
    with Session(engine) as session:
        item = session.get(Submission, uuid.UUID(submission_id))
        assert (
            item.queue_job_id == new_job
            and item.status == "checking"
            and not item.stop_requested
        )
    assert jobs[0] == jobs[1] and new_job not in jobs
    assert client.post(path + f"/{submission_id}/stop", headers=auth).status_code == 200


def test_guided_late_receipt_preserves_pre_freeze_exposure(ready):
    from app.model_config.service import lock_owner
    from app.training.evaluation_models import Evaluation
    from app.training.evaluation_worker import freeze
    from app.training.models import TrainingRun

    auth, identity, config, *_ = ready
    help_id = demo(ready)
    published = publish(auth, identity, help_id)
    with Session(engine) as session:
        run = session.get(TrainingRun, uuid.UUID(identity))
        lock_owner(session, run.user_id)
        evaluation = Evaluation(
            run_id=run.id,
            inputs={},
            case_snapshot=run.candidate,
            sources=run.sources,
            config_version=uuid.UUID(config["version"]),
            destination=config["service_url"],
            model_id=config["model_id"],
        )
        freeze(session, evaluation)
        session.commit()
        boundary = evaluation.frozen_sequence
    result = receipt(auth, identity, published)
    assert result.status_code == 200
    unknown, delivered = result.json()["deliveries"]
    assert unknown["status"] == "delivery_unknown"
    assert (
        delivered["exposure_sequence"]
        == unknown["sequence"]
        < boundary
        < delivered["sequence"]
    )
    assert delivered["direction"] == "directional"
    with Session(engine) as session:
        assert session.get(Evaluation, uuid.UUID(identity)).frozen_sequence == boundary


def test_practice_stop_before_actual_http_has_no_new_dispatch_then_explicit_retry(
    ready, provider
):
    from pathlib import Path

    auth, identity, config, _, control = ready
    help_id = demo(ready)
    receipt(auth, identity, publish(auth, identity, help_id))
    path = url(identity, help_id)
    options = json.loads(control.read_text())
    options["before_http"] = True
    control.write_text(json.dumps(options))
    submitted = body(config)
    assert client.post(path, headers=auth, json=submitted).status_code == 202
    deadline = time.monotonic() + 8
    while not Path(str(control) + ".blocked").exists():
        assert time.monotonic() < deadline
        time.sleep(0.02)
    assert (
        client.post(path + f"/{submitted['request_id']}/stop", headers=auth).status_code
        == 200
    )
    assert len(provider["requests"]) == 2
    options["before_http"] = False
    control.write_text(json.dumps(options))
    assert (
        client.post(
            path + f"/{submitted['request_id']}/retry", headers=auth
        ).status_code
        == 202
    )
    result = wait_practice(auth, path)
    assert result["completed"] and len(provider["requests"]) == 3
    assert len(result["records"]["submissions"][0]["attempts"]) == 2
    context = json.loads(provider["requests"][-1]["messages"][1]["content"])
    assert (
        len(context["judgments"]) == 1
        and "rubric" not in context
        and "help_boundary" not in json.dumps(context)
    )


def test_guided_inspection_retries_keep_six_attempt_budget_and_no_delivery(
    ready, provider
):
    auth, identity, config, *_ = ready
    provider["mode"] = "limited"
    item, _ = request(auth, identity, config, kind="demonstration")
    assert len(wait(auth, identity, item["id"])["attempts"]) == 3
    endpoint = f"/api/v1/training/tasks/{identity}/help/{item['id']}/retry"
    assert client.post(endpoint, headers=auth).status_code == 202
    result = wait(auth, identity, item["id"])
    assert (
        len(result["attempts"]) == 6
        and result["deliveries"] == []
        and not result["can_retry"]
    )
    assert client.post(endpoint, headers=auth).status_code == 409
