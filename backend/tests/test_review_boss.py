"""Actual released-stage qualification survives the review interpretation seam."""

import uuid

import pytest
from sqlmodel import Session, select

from app.core.db import engine
from app.model_config.service import lock_owner
from app.models import User
from app.training.boss_models import BossPromotion
from app.training.boss_stages import STAGES
from app.training.evaluation_models import Evaluation
from app.training.independent_service import record_frozen
from app.training.models import TrainingRun
from tests import test_training
from tests.stage_scenarios import REFERENCE, candidate, grade
from tests.test_accounts import client
from tests.test_boss_api import seed_points
from tests.test_boss_api import start as boss_start
from tests.test_evaluations import (
    endpoint as evaluation_endpoint,
)
from tests.test_evaluations import (
    wait as wait_evaluation,
)
from tests.test_model_config import account, save
from tests.test_review_history import evidence
from tests.test_reviews import consent, marker, options, start, wait
from tests.test_submissions import wait_submission

provider = test_training.provider


@pytest.mark.parametrize("missing_domain", [False, True])
def test_review_retains_each_boss_facet_grounding_and_never_promotes_on_reentry(
    tmp_path, provider, missing_domain
):
    stage = STAGES[-2]
    owner, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    seed_points(owner, config, stage.launch_points)
    with Session(engine) as session:
        user = session.get(User, owner)
        user.level = stage.from_level
        session.add(user)
        session.commit()

    def initial(context):
        result = grade(context)
        for item in result["items"]:
            item["conclusion"] = "unclear"
            item["gap"] = "受控原评分尚未确认原理由的含义"
        return result

    def reviewed(context):
        result = grade(context)
        if missing_domain:
            result["items"][0]["reason_claims"].pop()
        return {
            "decision": "corrected",
            "explanation": "仅重新核对冻结原答及其证据",
            "grading": result,
        }

    provider.update(
        candidate=candidate, grading=initial, review=reviewed, source_text=REFERENCE
    )
    response = boss_start(auth, config, expected_stage=stage.model_dump(mode="json"))
    assert response.status_code == 202, response.text
    identity = response.json()["id"]
    process, control = test_training.start_worker(tmp_path, provider, identity)
    try:
        assert test_training.wait_run(auth, identity).json()["status"] == "completed"
        response = client.post(
            f"/api/v1/training/tasks/{identity}/submissions",
            headers=auth,
            json={
                **consent(config),
                "request_id": str(uuid.uuid4()),
                "evaluate_after_submit": True,
                "answers": [
                    {
                        "judgment_id": m.judgment_id,
                        "value": 0,
                        "reason": "依据各域观察以及该材料对应记录判断。",
                    }
                    for m in stage.mandatory
                ],
            },
        )
        assert response.status_code == 202, response.text
        assert wait_submission(auth, identity)["awarded_points"] == 10
        assert wait_evaluation(auth, identity)["status"] == "needs_clarification"
        response = client.post(
            evaluation_endpoint(identity) + "/clarification",
            headers=auth,
            json={"answers": None},
        )
        assert response.status_code == 202
        original = response.json()
        options(control, review_before_settle=True)
        start(auth, identity, config)
        marker(control, ".review_settling")

        def reenter():
            with Session(engine) as session:
                lock_owner(session, owner)
                run = session.get(TrainingRun, uuid.UUID(identity))
                record_frozen(session, run, session.get(Evaluation, run.id))
                session.commit()
                assert session.get(User, owner).level == stage.from_level
                assert (
                    session.exec(
                        select(BossPromotion).where(BossPromotion.user_id == owner)
                    ).all()
                    == []
                )

        reenter()
        pending = evidence(auth)
        assert len(pending) == len(stage.mandatory)
        assert all(
            s["history"][0]["evidence"]["outcome"] == "pending"
            and not s["history"][0]["counted"]
            for s in pending
        )
        assert (
            client.get(f"/api/v1/boss/tasks/{identity}", headers=auth).json()[
                "decision"
            ]
            is None
        )
        options(control, review_before_settle=False)
        assert wait(auth, identity)["decision"] == "corrected"
        reenter()
        states = evidence(auth)
        assert len(states) == len(stage.mandatory)
        for state in states:
            expected = (
                "unclear"
                if missing_domain
                and state["target"]["capability_id"] == "performance.bottleneck"
                else "independent_pass_candidate"
            )
            assert state["history"][0]["evidence"]["outcome"] == expected
        assert (
            client.get(evaluation_endpoint(identity), headers=auth).json()["result"]
            == original["result"]
        )
        assert (
            wait_submission(auth, identity)["total_points"] == stage.launch_points + 10
        )
    finally:
        options(control, review_before_settle=False)
        test_training.stop_worker(process)
