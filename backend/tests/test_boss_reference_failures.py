"""Real bounded-history failure/cancellation paths; admission is a fixture here."""

import time
import uuid

import pytest
from sqlmodel import Session

from app.core.db import engine
from app.models import User
from app.training.boss_stages import PROMOTION_STAGES
from app.training.independent_models import IndependentWork
from app.training.models import TrainingRun
from tests import test_training
from tests.stage_scenarios import REFERENCE, candidate, public_history_cases
from tests.test_accounts import client
from tests.test_boss_api import seed_points, start
from tests.test_model_config import account, save

provider = test_training.provider


def admit(provider, count):
    owner, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    seed_points(owner, config, 6000)
    with Session(engine) as session:
        user = session.get(User, owner)
        user.level = "传奇程序员"
        session.add(user)
        for case, sources in public_history_cases(count):
            session.add(
                TrainingRun(
                    user_id=owner,
                    config_version=uuid.UUID(config["version"]),
                    destination=config["service_url"],
                    model_id=config["model_id"],
                    target=case.target.model_dump(),
                    selection={"entry": "controlled_fixture"},
                    candidate=case.model_dump(mode="json"),
                    sources=[s.model_dump(mode="json") for s in sources],
                    status="completed",
                    code="ready",
                )
            )
        session.commit()
    provider.update(candidate=candidate, source_text=REFERENCE)
    response = start(
        auth, config, expected_stage=PROMOTION_STAGES[-1].model_dump(mode="json")
    )
    assert response.status_code == 202, response.text
    return auth, config, response.json()["id"]


def test_missing_pair_cannot_publish_or_spend_calls_that_cannot_finish(
    tmp_path, provider
):
    auth, _, identity = admit(provider, 600)

    def missing(payload):
        value = candidate(payload)
        if "comparisons" in value:
            value["comparisons"].pop()
        return value

    provider["candidate"] = missing
    process, _ = test_training.start_worker(tmp_path, provider, identity)
    try:
        result = test_training.wait_run(auth, identity).json()
        assert (
            result["status"] == "failed" and result["code"] == "comparison_capacity"
        ), result
        assert "未完成的片未核对" in result["message"] and result["case"] is None
        assert len(provider["requests"]) == len(result["attempts"]) == 2
        assert [a["code"] for a in result["attempts"]] == ["ok", "invalid_candidate"]
        assert all(
            a["prompt_tokens"] == 11
            and a["completion_tokens"] == 9
            and a["total_tokens"] == 20
            for a in result["attempts"]
        )
        with Session(engine) as session:
            work = session.get(IndependentWork, uuid.UUID(identity))
            assert work.candidate and len(work.comparison_plan["batches"]) == 3
            assert work.comparison_results == [] and work.novelty is None
        boss = client.get(f"/api/v1/boss/tasks/{identity}", headers=auth).json()
        assert (
            boss["decision"] is None
            and boss["points"] == 6000
            and boss["promotion_id"] is None
        )
    finally:
        test_training.stop_worker(process)


@pytest.mark.parametrize("revoke", [False, True])
def test_reference_stream_cancel_preserves_partial_usage_and_private_plan(
    tmp_path, provider, revoke
):
    auth, config, identity = admit(provider, 2)
    provider["modes"] = ["ok", "partial_usage"]
    process, control = test_training.start_worker(
        tmp_path, provider, identity, observe_usage=True
    )
    try:
        marker = type(control)(str(control) + ".usage_received")
        deadline = time.monotonic() + 15
        while not marker.exists():
            assert time.monotonic() < deadline, "consumer did not receive partial usage"
            time.sleep(0.02)
        with Session(engine) as session:
            plan = session.get(IndependentWork, uuid.UUID(identity)).comparison_plan
        if revoke:
            stopped = client.request(
                "DELETE",
                "/api/v1/model-config",
                headers=auth,
                params={"expected_version": config["version"]},
            )
            assert stopped.status_code == 204, stopped.text
        else:
            stopped = client.post(
                f"/api/v1/training/tasks/{identity}/stop", headers=auth
            )
            assert stopped.status_code == 200, stopped.text
        result = test_training.wait_run(auth, identity).json()
        assert result["status"] == "stopped" and result["case"] is None, result
        assert len(provider["requests"]) == len(result["attempts"]) == 2
        assert result["attempts"][1]["prompt_tokens"] == 11
        assert result["attempts"][1]["completion_tokens"] is None
        assert result["attempts"][1]["total_tokens"] == 20
        with Session(engine) as session:
            work = session.get(IndependentWork, uuid.UUID(identity))
            assert work.comparison_plan == plan and work.comparison_results == []
        provider["release"].set()
        retried = client.post(
            f"/api/v1/training/tasks/{identity}/independent/retry", headers=auth
        )
        if revoke:
            assert retried.status_code == 409
        else:
            assert retried.status_code == 202, retried.text
            final = test_training.wait_run(auth, identity).json()
            assert final["status"] == "completed", final
            assert len(final["attempts"]) == len(provider["requests"]) == 3
            with Session(engine) as session:
                assert (
                    session.get(IndependentWork, uuid.UUID(identity)).comparison_plan
                    == plan
                )
    finally:
        provider["release"].set()
        test_training.stop_worker(process)
