import uuid

import pytest
from sqlmodel import Session, select

from app.core.db import engine
from app.training.boss import FIRST_STAGE
from app.training.boss_models import BossAttempt, BossPromotion
from app.training.models import TrainingRun
from app.training.submission_models import PracticeAward, Submission
from tests import test_training
from tests.boss_scenarios import REFERENCE, candidate, grade
from tests.test_accounts import client
from tests.test_evaluations import wait
from tests.test_model_config import account, save
from tests.test_submissions import wait_submission

provider = test_training.provider


def seed_points(owner, config, points=100):
    with Session(engine) as session:
        for _ in range(points // 10):
            run = TrainingRun(
                user_id=owner,
                config_version=uuid.UUID(config["version"]),
                destination=config["service_url"],
                model_id=config["model_id"],
                target=FIRST_STAGE.mandatory[0].target.model_dump(),
                selection={
                    "catalog_version": FIRST_STAGE.catalog_version,
                    "goal": "synthetic completed practice",
                },
                status="failed",
            )
            session.add(run)
            session.flush()
            original = Submission(
                run_id=run.id,
                config_version=run.config_version,
                destination=run.destination,
                model_id=run.model_id,
                answers=[{"judgment_id": "seed", "value": 0, "reason": "controlled"}],
                input_hash=str(uuid.uuid4()),
                status="completed",
            )
            session.add(original)
            session.flush()
            session.add(
                PracticeAward(run_id=run.id, submission_id=original.id, user_id=owner)
            )
        session.commit()


def start(auth, config, **changes):
    return client.post(
        "/api/v1/boss/start",
        headers=auth,
        json={
            "request_id": str(uuid.uuid4()),
            "expected_stage": FIRST_STAGE.model_dump(mode="json"),
            "expected_config_version": config["version"],
            "disclosure_accepted": True,
        }
        | changes,
    )


def answer(auth, identity, config, wrong=False):
    return client.post(
        f"/api/v1/training/tasks/{identity}/submissions",
        headers=auth,
        json={
            "request_id": str(uuid.uuid4()),
            "answers": [
                {
                    "judgment_id": m.judgment_id,
                    "value": 1 if wrong and m.judgment_id == "boss-cause" else 0,
                    "reason": "依据该判断对应的实际记录与验证结果决定。",
                }
                for m in FIRST_STAGE.mandatory
            ],
            "expected_config_version": config["version"],
            "disclosure_accepted": True,
            "evaluate_after_submit": True,
        },
    )


def test_stage_visible_before_start_owner_points_and_forgery():
    owner, auth = account()
    config = save(auth).json()
    assert client.get("/api/v1/boss/access").status_code == 401
    _, unverified = account(False)
    assert client.get("/api/v1/boss/access", headers=unverified).status_code == 403
    access = client.get("/api/v1/boss/access", headers=auth)
    assert (
        access.headers["cache-control"] == "no-store"
        and len(access.json()["stage"]["mandatory"]) == 3
    )
    seed_points(owner, config, 90)
    assert start(auth, config).status_code == 409
    seed_points(owner, config, 10)
    assert client.get("/api/v1/boss/access", headers=auth).json()["can_start"]
    assert start(auth, config, disclosure_accepted=False).status_code == 422
    assert (
        start(auth, config, expected_config_version=str(uuid.uuid4())).status_code
        == 409
    )
    stale = FIRST_STAGE.model_dump(mode="json")
    stale["catalog_version"] = "old-catalog"
    assert start(auth, config, expected_stage=stale).status_code == 409
    result = start(auth, config)
    assert result.status_code == 202, result.text
    identity = result.json()["id"]
    try:
        replay = start(auth, config, request_id=identity)
        assert replay.status_code == 202 and replay.json()["id"] == identity
        assert start(auth, config).status_code == 409
        assert result.json()["boss_stage"] == FIRST_STAGE.model_dump(mode="json")
        assert result.json()["case"] is None
        _, other = account()
        assert (
            client.get(f"/api/v1/boss/tasks/{identity}", headers=other).status_code
            == 404
        )
        assert start(auth, config, points=9999).status_code == 422
        with Session(engine) as session:
            assert session.get(BossAttempt, uuid.UUID(identity)).launch_points == 100
            assert (
                session.exec(
                    select(BossPromotion).where(BossPromotion.user_id == owner)
                ).all()
                == []
            )
    finally:
        client.post(f"/api/v1/training/tasks/{identity}/stop", headers=auth)


@pytest.mark.parametrize("wrong", [False, True])
def test_real_boss_generation_grading_award_promotion_and_three_target_projection(
    tmp_path, provider, wrong
):
    owner, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    seed_points(owner, config)
    provider.update(candidate=candidate, grading=grade, source_text=REFERENCE)
    result = start(auth, config)
    assert result.status_code == 202, result.text
    identity = result.json()["id"]
    process, _ = test_training.start_worker(tmp_path, provider, identity)
    try:
        ready = test_training.wait_run(auth, identity).json()
        assert ready["status"] == "completed", ready
        assert len(ready["case"]["judgments"]) == 3 and "PRIVATE_BOSS_HELP" not in str(
            ready
        )
        submitted = answer(auth, identity, config, wrong)
        assert submitted.status_code == 202, submitted.text
        assert wait_submission(auth, identity)["awarded_points"] == 10
        evaluated = wait(auth, identity)
        assert evaluated["status"] == "completed"
        assert (
            "Boss晋升" in evaluated["message"]
            and "不直接更新等级" not in evaluated["message"]
        )
        result = client.get(f"/api/v1/boss/tasks/{identity}", headers=auth).json()
        assert result["points"] == 110 and result["current_level"] == (
            "小白程序员" if wrong else "初级程序员"
        ), result
        assert bool(result["promotion_id"]) is (not wrong)
        states = client.get("/api/v1/capabilities/evidence", headers=auth).json()[
            "states"
        ]
        assert len(states) == 3, states
        entries = [s["history"][0]["evidence"] for s in states]
        assert (
            len({e["original_id"] for e in entries})
            == len({e["order"] for e in entries})
            == 1
        )
        assert {e["judgment_ids"][0] for e in entries} == {
            m.judgment_id for m in FIRST_STAGE.mandatory
        }
        assert [
            s["target"]["capability_id"]
            for s in states
            if s["status"] == "needs_consolidation"
        ] == (["frontend.state"] if wrong else [])
        assert len(provider["requests"]) == 4
        with Session(engine) as session:
            assert len(
                session.exec(
                    select(BossPromotion).where(BossPromotion.user_id == owner)
                ).all()
            ) == (0 if wrong else 1)
    finally:
        test_training.stop_worker(process)


@pytest.mark.parametrize("late_wrong", [False, True])
def test_two_accepted_bosses_keep_late_result_but_only_one_promotion(
    tmp_path, provider, late_wrong
):
    owner, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    seed_points(owner, config)
    provider.update(candidate=candidate, grading=grade, source_text=REFERENCE)
    older = start(auth, config).json()["id"]
    process, _ = test_training.start_worker(tmp_path, provider, older)
    try:
        assert test_training.wait_run(auth, older).json()["status"] == "completed"
        provider["candidate"] = lambda payload: candidate(payload, 1)
        newer_response = start(auth, config)
        assert newer_response.status_code == 202, newer_response.text
        newer = newer_response.json()["id"]
        assert test_training.wait_run(auth, newer).json()["status"] == "completed"
        assert answer(auth, newer, config).status_code == 202
        assert wait_submission(auth, newer)["awarded_points"] == 10
        assert wait(auth, newer)["status"] == "completed"
        assert client.get(f"/api/v1/boss/tasks/{newer}", headers=auth).json()[
            "promotion_id"
        ]
        assert start(auth, config).status_code == 409
        assert answer(auth, older, config, late_wrong).status_code == 202
        assert wait_submission(auth, older)["awarded_points"] == 10
        assert wait(auth, older)["status"] == "completed"
        state = client.get(f"/api/v1/boss/tasks/{older}", headers=auth).json()
        assert state["current_level"] == "初级程序员" and state["points"] == 120
        assert state["promotion_id"] is None
        assert state["decision"]["outcome"] == (
            "evidenced_fail" if late_wrong else "independent_pass_candidate"
        )
        assert [s["judgment_id"] for s in state["decision"]["shortfalls"]] == (
            ["boss-cause"] if late_wrong else []
        )
        for _ in range(2):
            assert (
                client.get(f"/api/v1/boss/tasks/{older}", headers=auth).json() == state
            )
        with Session(engine) as session:
            assert (
                len(
                    session.exec(
                        select(BossPromotion).where(BossPromotion.user_id == owner)
                    ).all()
                )
                == 1
            )
        assert len(provider["requests"]) == 8
    finally:
        test_training.stop_worker(process)


@pytest.mark.parametrize("timing", ["before", "late_receipt", "after_freeze"])
def test_boss_help_exposure_freeze_and_late_receipt_preserve_promotion_boundary(
    tmp_path, provider, timing
):
    from app.training.concept_models import HelpDelivery
    from tests.test_concepts import receipt
    from tests.test_independent_api import confirmed_publication
    from tests.test_practices import guided_coach

    owner, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    seed_points(owner, config)
    provider.update(
        candidate=candidate,
        grading=grade,
        source_text=REFERENCE,
        coach=guided_coach,
    )
    identity = start(auth, config).json()["id"]
    process, _ = test_training.start_worker(tmp_path, provider, identity)
    try:
        assert test_training.wait_run(auth, identity).json()["status"] == "completed"
        if timing != "after_freeze":
            publication = confirmed_publication((auth, identity, config))
            if timing == "before":
                assert receipt(auth, identity, publication).status_code == 200
        assert answer(auth, identity, config).status_code == 202
        assert wait_submission(auth, identity)["awarded_points"] == 10
        assert wait(auth, identity)["status"] == "completed"
        initial = client.get(f"/api/v1/boss/tasks/{identity}", headers=auth).json()
        assert (
            initial["decision"]["outcome"]
            == {
                "before": "practice",
                "late_receipt": "pending_delivery",
                "after_freeze": "independent_pass_candidate",
            }[timing]
        ), initial
        assert bool(initial["promotion_id"]) == (timing == "after_freeze")
        if timing == "after_freeze":
            publication = confirmed_publication((auth, identity, config))
        with Session(engine) as session:
            exposure = [
                (d.id, d.exposure_sequence)
                for d in session.exec(
                    select(HelpDelivery).where(
                        HelpDelivery.run_id == uuid.UUID(identity)
                    )
                ).all()
            ]
        calls = len(provider["requests"])
        assert (
            client.delete(
                "/api/v1/model-config",
                headers=auth,
                params={"expected_version": config["version"]},
            ).status_code
            == 204
        )
        assert receipt(auth, identity, publication).status_code == 200
        assert receipt(auth, identity, publication).status_code == 200
        final = client.get(f"/api/v1/boss/tasks/{identity}", headers=auth).json()
        assert final["decision"]["outcome"] == (
            "independent_pass_candidate" if timing == "after_freeze" else "practice"
        ), final
        assert final["promotion_id"] == initial["promotion_id"]
        assert final["current_level"] == (
            "初级程序员" if timing == "after_freeze" else "小白程序员"
        )
        assert final["decision"]["shortfalls"] == [] and final["points"] == 110
        assert len(provider["requests"]) == calls
        with Session(engine) as session:
            records = session.exec(
                select(HelpDelivery).where(HelpDelivery.run_id == uuid.UUID(identity))
            ).all()
            assert set(exposure) <= {(d.id, d.exposure_sequence) for d in records}
            assert {d.exposure_sequence for d in records} == {
                sequence for _, sequence in exposure
            }
            assert len([d for d in records if d.status == "delivered"]) == 1
            assert len([d for d in records if d.status == "delivery_unknown"]) == 1
    finally:
        test_training.stop_worker(process)


@pytest.mark.parametrize("problem", ["unclear", "missing_source", "missing_judgment"])
def test_unverified_mandatory_coverage_never_publishes_or_awards(
    tmp_path, provider, problem
):
    import json

    def broken(payload):
        value = candidate(payload)
        if "new" in json.loads(payload["messages"][1]["content"]):
            if problem == "unclear":
                value["boss_coverage"][1]["assessment"] = "unclear"
            elif problem == "missing_source":
                value["boss_coverage"][2]["source_id"] = "boss-network.trace"
        elif problem == "missing_judgment":
            value["judgments"] = value["judgments"][:2]
            value["rubric"] = value["rubric"][:2]
        return value

    owner, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    seed_points(owner, config)
    provider.update(candidate=broken, source_text=REFERENCE)
    identity = start(auth, config).json()["id"]
    process, _ = test_training.start_worker(tmp_path, provider, identity)
    try:
        run = test_training.wait_run(auth, identity).json()
        assert run["status"] == "failed" and run["case"] is None, run
        assert len(run["attempts"]) == (2 if problem == "missing_judgment" else 3)
        assert len(provider["requests"]) == len(run["attempts"])
        state = client.get(f"/api/v1/boss/tasks/{identity}", headers=auth).json()
        assert state["decision"] is None and state["promotion_id"] is None
        assert state["points"] == 100 and state["current_level"] == "小白程序员"
        assert (
            client.get("/api/v1/capabilities/evidence", headers=auth).json()["states"]
            == []
        )
    finally:
        test_training.stop_worker(process)


def test_concurrent_neutral_receipts_settle_under_owner_lock_once(
    tmp_path, provider, monkeypatch
):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy.exc import DBAPIError

    from app.models import User
    from app.training import concepts
    from tests.test_concepts import coach, publish, receipt
    from tests.test_concepts import request as request_help
    from tests.test_concepts import wait as wait_help

    def neutral(context):
        value = coach(context)
        if context["purpose"] == "concept_generate":
            value["evidence_ids"] = [context["evidence"][0]["id"]]
        return value

    owner, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    seed_points(owner, config)
    provider.update(
        candidate=candidate, grading=grade, source_text=REFERENCE, coach=neutral
    )
    identities = [start(auth, config).json()["id"]]
    process, _ = test_training.start_worker(tmp_path, provider, identities[0])
    try:
        assert (
            test_training.wait_run(auth, identities[0]).json()["status"] == "completed"
        )
        provider["candidate"] = lambda payload: candidate(payload, 1)
        identities.append(start(auth, config).json()["id"])
        assert (
            test_training.wait_run(auth, identities[1]).json()["status"] == "completed"
        )
        publications = []
        for identity in identities:
            item, _ = request_help(auth, identity, config)
            help_state = wait_help(auth, identity, item["id"])
            assert (
                help_state["status"] == "ready" and help_state["direction"] == "neutral"
            ), help_state
            assert not help_state["requires_independent_confirmation"]
            publications.append(publish(auth, identity, item["id"]))
            assert answer(auth, identity, config).status_code == 202
            assert wait_submission(auth, identity)["awarded_points"] == 10
            assert wait(auth, identity)["status"] == "completed"
            assert (
                client.get(f"/api/v1/boss/tasks/{identity}", headers=auth).json()[
                    "decision"
                ]["outcome"]
                == "pending_delivery"
            )
        both = threading.Barrier(2)
        acquired, release = threading.Event(), threading.Event()
        actual_lock = concepts.lock_owner

        def locked(session, user_id):
            both.wait(10)
            actual_lock(session, user_id)
            acquired.set()
            assert release.wait(10)

        with ThreadPoolExecutor(max_workers=2) as executor:
            with monkeypatch.context() as patch:
                patch.setattr(concepts, "lock_owner", locked)
                futures = [
                    executor.submit(receipt, auth, identity, publication)
                    for identity, publication in zip(
                        identities, publications, strict=True
                    )
                ]
                try:
                    assert acquired.wait(10)
                    with Session(engine) as session:
                        assert session.get(User, owner).level == "小白程序员"
                        assert not session.exec(
                            select(BossPromotion).where(BossPromotion.user_id == owner)
                        ).all()
                finally:
                    release.set()
                assert [f.result(10).status_code for f in futures] == [200, 200]
        calls = len(provider["requests"])
        states = [
            client.get(f"/api/v1/boss/tasks/{identity}", headers=auth).json()
            for identity in identities
        ]
        assert all(
            s["decision"]["outcome"] == "independent_pass_candidate"
            and s["current_level"] == "初级程序员"
            and s["points"] == 120
            for s in states
        )
        assert sum(bool(s["promotion_id"]) for s in states) == 1
        for identity, publication in zip(identities, publications, strict=True):
            assert receipt(auth, identity, publication).status_code == 200
        assert len(provider["requests"]) == calls == 12
        with Session(engine) as session:
            promotion = session.exec(
                select(BossPromotion).where(BossPromotion.user_id == owner)
            ).one()
            promotion.to_level = "不得改写"
            session.add(promotion)
            with pytest.raises(DBAPIError, match="boss facts are immutable"):
                session.commit()
            session.rollback()
            attempt = session.get(BossAttempt, uuid.UUID(identities[0]))
            attempt.launch_points = 9999
            session.add(attempt)
            with pytest.raises(DBAPIError, match="boss facts are immutable"):
                session.commit()
            session.rollback()
    finally:
        test_training.stop_worker(process)
