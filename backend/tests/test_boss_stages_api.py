"""Stage settlement integration; seeded admission here is NOT the 600-run test."""

import uuid

import pytest
from sqlmodel import Session, select

from app.core.db import engine
from app.models import User
from app.training.boss_models import BossPromotion
from app.training.boss_stages import STAGES
from app.training.independent_models import IndependentWork
from tests import test_training
from tests.stage_scenarios import REFERENCE, candidate, grade
from tests.test_accounts import client
from tests.test_boss_api import seed_points, start
from tests.test_evaluations import wait
from tests.test_model_config import account, save
from tests.test_submissions import wait_submission

provider = test_training.provider


@pytest.mark.parametrize(
    "stage,mixed",
    [(s, False) for s in STAGES] + [(STAGES[-2], True)],
    ids=[s.version for s in STAGES] + ["mixed-failure-missing-domain-grounding"],
)
def test_actual_stage_generation_facet_grading_and_single_promotion(
    tmp_path, provider, stage, mixed
):
    owner, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    seed_points(owner, config, stage.launch_points)
    with Session(engine) as session:
        user = session.get(User, owner)
        user.level = stage.from_level
        session.add(user)
        session.commit()
    access = client.get("/api/v1/boss/access", headers=auth).json()
    assert access["stage"] == stage.model_dump(mode="json") and access["can_start"]

    def controlled_grade(context):
        result = grade(context)
        if mixed:
            # A different item is a genuine failure. The diagnosis still claims
            # pass, but leaves one of its three required domains ungrounded.
            result["items"][0]["reason_claims"].pop()
        return result

    provider.update(
        candidate=candidate, grading=controlled_grade, source_text=REFERENCE
    )
    response = start(auth, config, expected_stage=stage.model_dump(mode="json"))
    assert response.status_code == 202, response.text
    identity = response.json()["id"]
    process, _ = test_training.start_worker(tmp_path, provider, identity)
    try:
        ready = test_training.wait_run(auth, identity).json()
        assert ready["status"] == "completed", ready
        assert {j["id"] for j in ready["case"]["judgments"]} == {
            m.judgment_id for m in stage.mandatory
        }
        submitted = client.post(
            f"/api/v1/training/tasks/{identity}/submissions",
            headers=auth,
            json={
                "request_id": str(uuid.uuid4()),
                "answers": [
                    {
                        "judgment_id": m.judgment_id,
                        "value": 1 if mixed and m.judgment_id == "risk" else 0,
                        "reason": "根据对应材料中的全部观察判断，并核对持久结果与反例。",
                    }
                    for m in stage.mandatory
                ],
                "expected_config_version": config["version"],
                "disclosure_accepted": True,
                "evaluate_after_submit": True,
            },
        )
        assert submitted.status_code == 202, submitted.text
        assert wait_submission(auth, identity)["awarded_points"] == 10
        evaluated = wait(auth, identity)
        assert evaluated["status"] == "completed", evaluated
        result = client.get(f"/api/v1/boss/tasks/{identity}", headers=auth).json()
        assert result["decision"]["outcome"] == (
            "evidenced_fail" if mixed else "independent_pass_candidate"
        ), result
        assert result["current_level"] == (
            stage.from_level if mixed else (stage.to_level or stage.from_level)
        ), result
        assert bool(result["promotion_id"]) == bool(stage.to_level and not mixed)
        states = client.get("/api/v1/capabilities/evidence", headers=auth).json()[
            "states"
        ]
        assert {s["target"]["capability_id"] for s in states} == {
            m.target.capability_id for m in stage.mandatory
        }
        for state in states:
            expected = "independent_pass_candidate"
            if mixed and state["target"]["capability_id"] == "performance.bottleneck":
                expected = "unclear"
            if mixed and state["target"]["capability_id"] == "requirements.tradeoff":
                expected = "evidenced_fail"
            assert state["history"][0]["evidence"]["outcome"] == expected, state
        with Session(engine) as session:
            work = session.get(IndependentWork, uuid.UUID(identity))
            assert work.history_snapshot is not None and work.history == []
            assert len(work.comparison_results) == 1
            assert len(
                session.exec(
                    select(BossPromotion).where(BossPromotion.user_id == owner)
                ).all()
            ) == bool(stage.to_level and not mixed)
        assert len(provider["requests"]) == 4
    finally:
        test_training.stop_worker(process)
