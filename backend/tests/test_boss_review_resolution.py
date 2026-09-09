"""Actual corrected-pass resolution, including help and old requirement cycles."""

import json

import pytest

from tests import boss_scenarios, test_training
from tests.test_accounts import client
from tests.test_boss_api import answer, seed_points
from tests.test_boss_api import start as boss_start
from tests.test_boss_revalidation import access, corrected
from tests.test_evaluations import wait as evaluation_wait
from tests.test_model_config import account, save
from tests.test_reviews import start as review_start
from tests.test_reviews import wait as review_wait
from tests.test_submissions import wait_submission

provider = test_training.provider


def third_case(payload):
    result = boss_scenarios.candidate(payload, 1)
    if "comparisons" in result:
        return result
    raw = json.dumps(result, ensure_ascii=False)
    for before, after in (
        ("tls_failed", "tcp_refused"),
        ("核对证书与TLS记录", "核对目标端口监听与连接拒绝记录"),
        ("older_session_overwrite", "optimistic_failure_not_rolled_back"),
        ("按会话归属拒绝旧回包", "失败回包后撤销未获确认的乐观状态"),
        ("database_not_checked", "transaction_commit_not_checked"),
        ("核对数据库记录与新会话读取", "核对事务提交与回滚后的持久结果"),
    ):
        raw = raw.replace(before, after)
    return json.loads(raw)


def passing_review(context):
    return {
        "decision": "corrected",
        "explanation": "原评分误读了被冻结的查证理由",
        "grading": boss_scenarios.grade(context),
    }


@pytest.fixture
def pending(tmp_path, provider):
    owner, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    seed_points(owner, config)
    provider.update(
        candidate=boss_scenarios.candidate,
        grading=boss_scenarios.grade,
        review=corrected,
        source_text=boss_scenarios.REFERENCE,
    )
    original = boss_start(auth, config).json()["id"]
    process, _ = test_training.start_worker(tmp_path, provider, original)
    try:
        assert test_training.wait_run(auth, original).json()["status"] == "completed"
        answer(auth, original, config)
        assert wait_submission(auth, original)["awarded_points"] == 10
        assert evaluation_wait(auth, original)["status"] == "completed"
        review_start(auth, original, config)
        assert review_wait(auth, original)["decision"] == "corrected"
        requirement = access(auth)["revalidations"][0]
        yield auth, config, requirement
    finally:
        test_training.stop_worker(process)


def attempt(pending, provider, candidate):
    auth, config, requirement = pending
    provider["candidate"] = candidate
    response = boss_start(
        auth,
        config,
        revalidation_of=requirement["promotion_id"],
        expected_revalidation_event_id=requirement["current_event_id"],
    )
    assert response.status_code == 202, response.text
    identity = response.json()["id"]
    assert test_training.wait_run(auth, identity).json()["status"] == "completed"
    return identity


def finish(pending, identity):
    auth, config, _ = pending
    answer(auth, identity, config)
    assert wait_submission(auth, identity)["awarded_points"] == 10
    value = evaluation_wait(auth, identity)
    if value["status"] == "needs_clarification":
        response = client.post(
            f"/api/v1/training/tasks/{identity}/evaluation/clarification",
            headers=auth,
            json={"answers": None},
        )
        assert response.status_code == 202, response.text
    else:
        assert value["status"] == "completed", value


@pytest.mark.parametrize("initial", ["fail", "unclear", "help"])
def test_corrected_valid_pass_resolves_only_frozen_independent_attempt(
    pending, provider, initial
):
    from tests.test_concepts import receipt
    from tests.test_independent_api import confirmed_publication
    from tests.test_practices import guided_coach

    auth, config, requirement = pending
    identity = attempt(
        pending, provider, lambda payload: boss_scenarios.candidate(payload, 1)
    )
    if initial == "help":
        provider["coach"] = guided_coach
        publication = confirmed_publication((auth, identity, config))
        assert receipt(auth, identity, publication).status_code == 200

    def grade(context):
        result = corrected(context)["grading"]
        if initial == "unclear":
            for item in result["items"]:
                item.update(conclusion="unclear", gap="原评分尚未确认理由含义")
        return result

    provider["grading"] = grade
    finish(pending, identity)
    assert access(auth)["revalidations"][0] == requirement
    provider["review"] = passing_review
    review_start(auth, identity, config)
    assert review_wait(auth, identity)["decision"] == "corrected"
    state = access(auth)
    result = client.get(f"/api/v1/boss/tasks/{identity}", headers=auth).json()
    assert result["decision"]["outcome"] == (
        "practice" if initial == "help" else "independent_pass_candidate"
    )
    assert state["revalidations"][0]["status"] == (
        "required" if initial == "help" else "resolved"
    )
    assert state["level"] == "初级程序员" and state["points"] == 120
    assert result["promotion_id"] is None


def test_old_cycle_corrected_pass_does_not_clear_new_requirement(pending, provider):
    auth, config, requirement = pending
    older = attempt(
        pending, provider, lambda payload: boss_scenarios.candidate(payload, 1)
    )
    provider["grading"] = lambda context: corrected(context)["grading"]
    finish(pending, older)
    provider["grading"] = boss_scenarios.grade
    newer = attempt(pending, provider, third_case)
    finish(pending, newer)
    assert access(auth)["revalidations"][0]["status"] == "resolved"
    provider["review"] = corrected
    review_start(auth, newer, config)
    assert review_wait(auth, newer)["decision"] == "corrected"
    current = access(auth)["revalidations"][0]
    assert (
        current["status"] == "required"
        and current["current_event_id"] != requirement["current_event_id"]
    )
    provider["review"] = passing_review
    review_start(auth, older, config)
    assert review_wait(auth, older)["decision"] == "corrected"
    state = access(auth)
    assert state["revalidations"][0] == current
    assert state["level"] == "初级程序员" and state["points"] == 130
