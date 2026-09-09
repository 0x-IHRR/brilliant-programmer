"""Review interpretation at original positions, with current real worker history."""

import json
import uuid

import pytest
from sqlmodel import Session

from app.capabilities.catalog import CATALOG
from app.core.db import engine
from app.model_config.service import lock_owner
from app.training.evaluation_models import Evaluation
from app.training.independent_service import record_frozen
from app.training.models import TrainingRun
from tests import test_independent_api as independent
from tests.capability_scenarios import comparisons, scenario
from tests.test_accounts import client
from tests.test_evaluations import (
    grading,
)
from tests.test_evaluations import (
    start as start_evaluation,
)
from tests.test_evaluations import (
    wait as wait_evaluation,
)
from tests.test_reviews import consent, endpoint, marker, options, start, wait
from tests.test_submissions import wait_submission
from tests.test_training import start_worker, stop_worker, wait_run

provider = independent.provider
frozen = independent.frozen
origin = independent.origin
checked = independent.checked


def actual_grade(context):
    result = grading(context)
    material = context["task"]["evidence"][0]
    fact, value = next(iter(material["facts"].items()))
    for item in result["items"]:
        item["grounding"][0].update(fact=fact, value=value)
        item["reason_claims"][0]["interpreted_fact_value"] = value
    return result


def corrected_fail(context):
    result = actual_grade(context)
    for item in result["items"]:
        item["conclusion"] = "evidenced_fail"
        item["interpreted_reasoning"] = 1
        item["counterexample_quote"] = next(
            r
            for r in context["task"]["rubric"]
            if r["judgment_id"] == item["judgment_id"]
        )["counterexample"]
        item["gap"] = "受控复核：原评分对这段理由的事实含义解释错误"
    return {
        "decision": "corrected",
        "explanation": "重新对照原答与原证据的真实约束；这是受控候选",
        "grading": result,
    }


def evidence(auth):
    response = client.get("/api/v1/capabilities/evidence", headers=auth)
    assert response.status_code == 200, response.text
    return response.json()["states"]


@pytest.mark.parametrize("already_opened", [False, True])
def test_pending_then_new_practice_and_original_order_replay_keeps_openings(
    tmp_path, provider, frozen, origin, already_opened
):
    auth, origin_id, config, _ = origin
    provider["grading"] = actual_grade
    provider["review"] = corrected_fail
    process, control = start_worker(tmp_path, provider, str(origin_id))
    run_ids = []
    try:
        for index in range(3):
            case = scenario(frozen[0], index)
            provider["candidate"] = lambda payload, case=case: (
                comparisons(json.loads(payload["messages"][1]["content"]))
                if "new" in json.loads(payload["messages"][1]["content"])
                else case.model_dump()
            )
            response = client.post(
                f"/api/v1/training/tasks/{origin_id}/independent",
                headers=auth,
                json={**consent(config), "request_id": str(uuid.uuid4())},
            )
            assert response.status_code == 202, response.text
            identity = response.json()["id"]
            run_ids.append(identity)
            assert wait_run(auth, identity).json()["status"] == "completed"
            submitted = client.post(
                f"/api/v1/training/tasks/{identity}/submissions",
                headers=auth,
                json={
                    **consent(config),
                    "request_id": str(uuid.uuid4()),
                    "answers": [
                        {
                            "judgment_id": "j1",
                            "value": 0,
                            "reason": "根据本案例材料中的持久结果和处理状态判断。",
                        }
                    ],
                },
            )
            assert submitted.status_code == 202, submitted.text
            assert wait_submission(auth, identity)["awarded_points"] == 10
            start_evaluation(auth, identity, config)
            assert wait_evaluation(auth, identity)["status"] == "completed"
            if index == 1:
                before = evidence(auth)[0]
                assert before["status"] == "verified" and before["streak"] == 2
                target = {**case.target.model_dump(), "difficulty": "进阶"}
                if already_opened:
                    opened = client.post(
                        "/api/v1/capabilities/open",
                        headers=auth,
                        json={"catalog_version": CATALOG.version, "target": target},
                    )
                    assert opened.status_code == 200, opened.text
                # Stop before acceptance, while retaining actual received usage.
                options(control, run_id=identity, review_before_settle=True)
                # Existing test worker binds its initial ID; start a correctly bound worker.
                stop_worker(process)
                process, control = start_worker(
                    tmp_path, provider, identity, review_before_settle=True
                )
                start(auth, identity, config)
                marker(control, ".review_settling")
                assert (
                    client.post(endpoint(identity) + "/stop", headers=auth).status_code
                    == 200
                )
                options(control, review_before_settle=False)
                pending = evidence(auth)[0]
                assert (
                    pending["streak"] == 1
                    and pending["history"][1]["evidence"]["outcome"] == "pending"
                )
                assert pending["history"][1]["evidence"]["review_decision"] == "pending"
                assert client.post(
                    "/api/v1/capabilities/open",
                    headers=auth,
                    json={"catalog_version": CATALOG.version, "target": target},
                ).status_code == (200 if already_opened else 409)
        # The new third record exists while review remains pending; no old map restore.
        during = evidence(auth)[0]
        assert len(during["history"]) == 3 and during["streak"] == 2
        assert wait_submission(auth, run_ids[-1])["total_points"] == 30
        assert (
            client.post(
                endpoint(run_ids[1]) + "/retry", headers=auth, json=consent(config)
            ).status_code
            == 202
        )
        assert wait(auth, run_ids[1])["decision"] == "corrected"
        after = evidence(auth)[0]
        assert [h["evidence"]["run_id"] for h in after["history"]] == run_ids
        assert [h["evidence"]["outcome"] for h in after["history"]] == [
            "independent_pass_candidate",
            "evidenced_fail",
            "independent_pass_candidate",
        ]
        assert [h["streak"] for h in after["history"]] == [1, 0, 1]
        assert (
            after["history"][1]["evidence"]["order"]
            == before["history"][1]["evidence"]["order"]
        )
        assert wait_submission(auth, run_ids[-1])["total_points"] == 30
        assert client.post(
            "/api/v1/capabilities/open",
            headers=auth,
            json={"catalog_version": CATALOG.version, "target": target},
        ).status_code == (200 if already_opened else 409)
        # Re-entry through the actual old feedback/help projection cannot reinstall old pass.
        with Session(engine) as session:
            run = session.get(TrainingRun, uuid.UUID(run_ids[1]))
            lock_owner(session, run.user_id)
            record_frozen(session, run, session.get(Evaluation, run.id))
            session.commit()
        assert evidence(auth) == [after]
    finally:
        options(control, review_before_settle=False)
        stop_worker(process)


def test_pending_stops_new_unlock_without_claiming_already_misgraded(checked, provider):
    auth, identity, config = checked
    independent.evaluate(checked)
    # Single candidate isn't enough even before review; pending must not grant it.
    provider["review"] = corrected_fail
    provider["mode"] = "limited"
    start(auth, identity, config)
    state = wait(auth, identity)
    assert state["decision"] == "pending" and state["opinion"] is None
    current = evidence(auth)[0]
    assert current["streak"] == 0 and not current["history"][0]["counted"]
    target = {**current["target"], "difficulty": "进阶"}
    assert (
        client.post(
            "/api/v1/capabilities/open",
            headers=auth,
            json={"catalog_version": CATALOG.version, "target": target},
        ).status_code
        == 409
    )


@pytest.mark.parametrize("timing", ["before", "late_receipt", "after_freeze"])
def test_review_and_late_receipt_preserve_actual_frozen_help_qualification(
    checked, provider, timing
):
    from tests.test_concepts import receipt

    auth, identity, config = checked
    if timing == "after_freeze":
        independent.evaluate(checked)
    publication = independent.confirmed_publication(checked)
    if timing == "before":
        assert receipt(auth, identity, publication).status_code == 200
    if timing != "after_freeze":
        independent.evaluate(checked)
    provider["review"] = lambda context: {
        "decision": "upheld",
        "explanation": "冻结证据支持维持原评分；不改变帮助交付事实",
        "grading": actual_grade(context),
    }
    start(auth, identity, config)
    assert wait(auth, identity)["decision"] == "upheld"
    current = evidence(auth)[0]
    assert current["history"][0]["evidence"]["outcome"] == (
        "independent_pass_candidate"
        if timing == "after_freeze"
        else "practice"
        if timing == "before"
        else "pending_delivery"
    )
    calls = len(provider["requests"])
    assert (
        client.delete(
            "/api/v1/model-config",
            headers=auth,
            params={"expected_version": config["version"]},
        ).status_code
        == 204
    )
    if timing != "before":
        assert receipt(auth, identity, publication).status_code == 200
    current = evidence(auth)[0]
    assert current["history"][0]["evidence"]["outcome"] == (
        "independent_pass_candidate" if timing == "after_freeze" else "practice"
    )
    assert current["history"][0]["counted"] == (timing == "after_freeze")
    assert len(provider["requests"]) == calls
