"""Real owner API / PostgreSQL / independent queue worker / controlled TLS."""

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlmodel import Session, select

from app.core.db import engine
from app.training.review_models import ScoreReview
from app.training.review_worker import claim, finish, record
from tests import test_evaluations as evaluation
from tests.test_accounts import client
from tests.test_model_config import FAKE_KEY, account, save
from tests.test_submissions import wait_submission
from tests.test_training import stop_worker

provider = evaluation.provider
ready = evaluation.ready


def endpoint(identity):
    return f"/api/v1/training/tasks/{identity}/review"


def consent(config):
    return {"disclosure_accepted": True, "expected_config_version": config["version"]}


def start(auth, identity, config, request_id=None):
    body = {**consent(config), "request_id": request_id or str(uuid.uuid4())}
    result = client.post(endpoint(identity), headers=auth, json=body)
    assert result.status_code == 202, result.text
    return result.json(), body


def wait(auth, identity):
    until = time.monotonic() + 15
    while time.monotonic() < until:
        result = client.get(endpoint(identity), headers=auth)
        assert result.status_code == 200, result.text
        data = result.json()
        if data["status"] not in {"queued", "running", "stopping"} and (
            data["status"] != "completed"
            or bool(data["attempts"])
            and data["attempts"][-1]["code"] == "ok"
        ):
            return data
        time.sleep(0.03)
    raise AssertionError(result.text)


def prepare(ready, provider, verdict="pass"):
    auth, identity, config, *_ = ready
    provider["review"] = reply
    provider["grading"] = lambda context: evaluation.grading(context, verdict)
    evaluation.start(auth, identity, config)
    original = evaluation.wait(auth, identity)
    if original["status"] == "needs_clarification":
        client.post(
            evaluation.endpoint(identity) + "/clarification",
            headers=auth,
            json={"answers": None},
        )
        original = evaluation.wait(auth, identity)
    assert original["status"] == "completed", original
    return original


def reply(context, decision="upheld"):
    return {
        "decision": decision,
        "explanation": "依据冻结原答和来源逐项核对；受控测试不证明模型语义质量",
        "grading": None if decision == "disputed" else evaluation.grading(context),
    }


@pytest.mark.parametrize("decision", ["upheld", "corrected", "disputed"])
def test_review_once_freezes_original_context_and_keeps_points(
    ready, provider, decision
):
    auth, identity, config, answer, *_ = ready
    original = prepare(
        ready, provider, "unclear" if decision == "corrected" else "pass"
    )
    provider["review"] = lambda context: reply(context, decision)
    accepted, body = start(auth, identity, config)
    result = wait(auth, identity)
    assert result["status"] == "completed" and result["decision"] == decision, result
    assert result["request_id"] == body["request_id"]
    assert result["attempts"][0]["total_tokens"] == 20
    assert result["attempts"][0]["config_version"] == config["version"]
    assert client.post(endpoint(identity), headers=auth, json=body).json() == result
    assert (
        client.post(
            endpoint(identity),
            headers=auth,
            json={**body, "request_id": str(uuid.uuid4())},
        ).status_code
        == 409
    )
    after = client.get(evaluation.endpoint(identity), headers=auth).json()
    assert (
        after["inputs"] == original["inputs"] and after["result"] == original["result"]
    )
    assert wait_submission(auth, identity)["awarded_points"] == 10
    context = json.loads(provider["requests"][-1]["messages"][1]["content"])
    assert set(context) == {
        "purpose",
        "task",
        "sources",
        "inputs",
        "original_grading",
        "rule_version",
        "schema",
    }
    assert context["inputs"]["original"] == [answer]
    assert "HIDDEN_HELP" not in json.dumps(context) and FAKE_KEY not in json.dumps(
        context
    )
    assert "snapshot" not in result and "key" not in result
    _, other = account()
    assert client.get(endpoint(identity), headers=other).status_code == 404
    assert client.get(endpoint(identity)).status_code == 401
    with Session(engine) as session:
        saved = session.get(ScoreReview, uuid.UUID(identity))
        saved.snapshot = {}
        session.add(saved)
        with pytest.raises(Exception, match="review snapshot is immutable"):
            session.commit()


def test_concurrent_acceptance_has_one_queue_and_one_opportunity(ready, provider):
    auth, identity, config, _, process, _ = ready
    prepare(ready, provider)
    stop_worker(process)
    body = {**consent(config), "request_id": str(uuid.uuid4())}
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(
                lambda _: client.post(endpoint(identity), headers=auth, json=body),
                range(2),
            )
        )
    assert [r.status_code for r in responses] == [202, 202]
    assert responses[0].json() == responses[1].json()
    with Session(engine) as session:
        assert (
            len(
                session.exec(
                    select(ScoreReview).where(ScoreReview.run_id == uuid.UUID(identity))
                ).all()
            )
            == 1
        )
    assert client.post(endpoint(identity) + "/stop", headers=auth).status_code == 200


def test_transient_six_budget_network_is_pending_not_disputed(ready, provider):
    auth, identity, config, *_ = ready
    prepare(ready, provider)
    provider["mode"] = "limited"
    start(auth, identity, config)
    result = wait(auth, identity)
    assert result["decision"] == "pending" and len(result["attempts"]) == 3
    assert (
        client.post(
            endpoint(identity) + "/retry", headers=auth, json=consent(config)
        ).status_code
        == 202
    )
    result = wait(auth, identity)
    assert result["decision"] == "pending" and len(result["attempts"]) == 6
    assert result["remaining_attempts"] == 0
    assert (
        client.post(
            endpoint(identity) + "/retry", headers=auth, json=consent(config)
        ).status_code
        == 409
    )
    assert len(provider["requests"]) == 9
    assert wait_submission(auth, identity)["awarded_points"] == 10


def test_durable_permanent_failure_prevents_crash_replay_new_config_keeps_history(
    ready, provider
):
    auth, identity, config, _, process, _ = ready
    prepare(ready, provider)
    stop_worker(process)
    start(auth, identity, config)
    uid = uuid.UUID(identity)
    with Session(engine) as session:
        job = session.get(ScoreReview, uid).queue_job_id
    attempt = claim(uid, job)
    assert attempt
    record(attempt.id, "authentication", {})
    # Exact crash window: durable permanent response exists, finish hasn't run.
    assert claim(uid, job) is None
    assert wait(auth, identity)["code"] == "authentication"
    assert (
        client.post(
            endpoint(identity) + "/retry", headers=auth, json=consent(config)
        ).status_code
        == 409
    )
    updated = save(
        auth, service_url=provider["url"], expected_version=config["version"]
    ).json()
    assert updated["version"] != config["version"]
    assert (
        client.post(
            endpoint(identity) + "/retry",
            headers=auth,
            json={**consent(updated), "disclosure_accepted": False},
        ).status_code
        == 422
    )
    assert (
        client.post(
            endpoint(identity) + "/retry", headers=auth, json=consent(updated)
        ).status_code
        == 202
    )
    with Session(engine) as session:
        new_job = session.get(ScoreReview, uid).queue_job_id
    assert new_job != job
    finish(uid, job, "internal_failure", "old worker")
    assert claim(uid, job) is None
    current = client.get(endpoint(identity), headers=auth).json()
    assert (
        current["status"] == "queued"
        and current["attempts"][0]["config_version"] == config["version"]
    )
    new_attempt = claim(uid, new_job)
    assert (
        new_attempt.number == 2
        and str(new_attempt.config_version) == updated["version"]
    )
    assert client.post(endpoint(identity) + "/stop", headers=auth).status_code == 200


@pytest.mark.parametrize("failure", ["storage", "revoked"])
def test_received_usage_survives_unsettled_result(ready, provider, failure):
    auth, identity, config, _, process, _ = ready
    prepare(ready, provider)
    stop_worker(process)
    start(auth, identity, config)
    uid = uuid.UUID(identity)
    with Session(engine) as session:
        item = session.get(ScoreReview, uid)
        job = item.queue_job_id
    attempt = claim(uid, job)
    record(
        attempt.id,
        "unknown",
        {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    )
    if failure == "revoked":
        assert (
            client.delete(
                "/api/v1/model-config",
                headers=auth,
                params={"expected_version": config["version"]},
            ).status_code
            == 204
        )
    else:
        finish(uid, job, "internal_failure", "controlled storage failure")
    # Late empty counts cannot erase received counts, nor label an unaccepted result ok.
    record(attempt.id, "cancelled", {})
    result = client.get(endpoint(identity), headers=auth).json()
    assert result["decision"] == "pending" and result["opinion"] is None
    assert result["attempts"][0]["total_tokens"] == 18
    assert wait_submission(auth, identity)["awarded_points"] == 10


def marker(control, suffix):
    from pathlib import Path

    until = time.monotonic() + 10
    while not Path(str(control) + suffix).exists():
        assert time.monotonic() < until
        time.sleep(0.02)


def options(control, **changes):
    value = json.loads(control.read_text())
    value.update(changes)
    control.write_text(json.dumps(value))


def test_real_auth_response_crash_recovery_never_calls_again(ready, provider, tmp_path):
    from tests.test_training import start_worker

    auth, identity, config, _, process, control = ready
    prepare(ready, provider)
    provider["mode"] = "auth"
    options(control, review_before_finish=True)
    start(auth, identity, config)
    marker(control, ".review_finishing")
    process.kill()
    process.wait(5)
    current = client.get(endpoint(identity), headers=auth).json()
    assert (
        current["status"] == "running"
        and current["attempts"][0]["code"] == "authentication"
    )
    count = len(provider["requests"])
    time.sleep(0.7)
    resumed, _ = start_worker(tmp_path, provider, identity)
    try:
        result = wait(auth, identity)
        assert result["code"] == "authentication" and result["decision"] == "pending"
        assert len(result["attempts"]) == 1 and len(provider["requests"]) == count
    finally:
        stop_worker(resumed)


@pytest.mark.parametrize("failure", ["storage", "revoked", "stop"])
def test_actual_received_result_then_settle_failure_or_stop_keeps_usage(
    ready, provider, failure
):
    auth, identity, config, _, _, control = ready
    prepare(ready, provider)
    options(control, review_before_settle=True)
    start(auth, identity, config)
    marker(control, ".review_settling")
    current = client.get(endpoint(identity), headers=auth).json()
    assert current["attempts"][0]["total_tokens"] == 20
    if failure == "storage":
        options(control, review_before_settle=False, review_storage_failure=True)
    elif failure == "revoked":
        assert (
            client.delete(
                "/api/v1/model-config",
                headers=auth,
                params={"expected_version": config["version"]},
            ).status_code
            == 204
        )
        options(control, review_before_settle=False)
    else:
        assert (
            client.post(endpoint(identity) + "/stop", headers=auth).status_code == 200
        )
        options(control, review_before_settle=False)
    result = wait(auth, identity)
    assert result["decision"] == "pending" and result["opinion"] is None
    assert result["attempts"][0]["total_tokens"] == 20
    assert result["attempts"][0]["code"] != "ok"
    assert wait_submission(auth, identity)["awarded_points"] == 10
    if failure == "stop":
        assert (
            client.post(
                endpoint(identity) + "/retry", headers=auth, json=consent(config)
            ).status_code
            == 202
        )
        result = wait(auth, identity)
        assert result["decision"] == "upheld" and len(result["attempts"]) == 2


@pytest.mark.parametrize("format", ["json", "sse"])
def test_secret_or_forged_review_never_becomes_a_conclusion(ready, provider, format):
    auth, identity, config, *_ = ready
    prepare(ready, provider)

    def leak(context):
        result = reply(context)
        result["explanation"] = FAKE_KEY
        return result

    provider.update(review=leak, escaped_output=True, response_format=format)
    start(auth, identity, config)
    result = wait(auth, identity)
    assert result["decision"] == "pending" and result["opinion"] is None
    assert (
        result["code"] == "invalid_response"
        and result["attempts"][0]["total_tokens"] == 20
    )
    assert FAKE_KEY not in json.dumps(result)
    assert (
        client.post(
            endpoint(identity) + "/retry", headers=auth, json=consent(config)
        ).status_code
        == 409
    )
    assert len(provider["requests"]) == 4
