"""Actual Boss and review calls; a retest cannot rehabilitate an old callback."""

import json
import uuid

from sqlmodel import Session

from app.core.db import engine
from app.model_config.service import lock_owner
from app.training.boss_service import mark_reviewed_promotion
from app.training.evaluation_models import Evaluation
from app.training.independent_service import record_frozen
from app.training.models import TrainingRun
from app.training.review_models import ScoreReview
from app.training.schema import Source
from tests import boss_scenarios, test_training
from tests import test_boss_review_resolution as resolution
from tests.test_accounts import client
from tests.test_boss_api import answer, seed_points
from tests.test_boss_api import start as boss_start
from tests.test_boss_revalidation import access, corrected
from tests.test_evaluations import wait as evaluation_wait
from tests.test_independent_api import wait_until
from tests.test_model_config import account, save
from tests.test_quality_api import publish, report_for
from tests.test_reviews import start as review_start
from tests.test_reviews import wait as review_wait
from tests.test_submissions import wait_submission

provider = test_training.provider
pending = resolution.pending


def actual(identity):
    with Session(engine) as session:
        run = session.get(TrainingRun, uuid.UUID(identity))
        return run.user_id, [Source.model_validate(s) for s in run.sources]


def test_boss_failure_during_grading_blocks_old_callbacks_new_challenge_can_promote(
    tmp_path, provider
):
    owner, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    seed_points(owner, config)
    provider.update(
        candidate=boss_scenarios.candidate,
        grading=boss_scenarios.grade,
        source_text=boss_scenarios.REFERENCE,
    )
    identity = boss_start(auth, config).json()["id"]
    process, control = test_training.start_worker(
        tmp_path, provider, identity, before_quality_settle=True
    )
    try:
        assert test_training.wait_run(auth, identity).json()["status"] == "completed"
        answer(auth, identity, config)
        wait_until(type(control)(str(control) + ".quality_settling").exists)
        _, sources = actual(identity)
        failed, _ = report_for(owner, config, failed=True, sources=sources)
        publish(failed)
        options = json.loads(control.read_text())
        options["before_quality_settle"] = False
        control.write_text(json.dumps(options))
        assert evaluation_wait(auth, identity)["status"] == "completed"
        old = client.get(f"/api/v1/boss/tasks/{identity}", headers=auth).json()
        assert old["promotion_id"] is None and old["disposition"] == "blocked_quality"
        assert wait_submission(auth, identity)["awarded_points"] == 10
        retest, _ = report_for(
            owner, config, supersedes=failed.artifact_id, sources=sources
        )
        publish(retest)
        with Session(engine) as session:
            lock_owner(session, owner)
            run = session.get(TrainingRun, uuid.UUID(identity))
            record_frozen(session, run, session.get(Evaluation, run.id))
            session.commit()
        assert client.get(f"/api/v1/boss/tasks/{identity}", headers=auth).json() == old
        provider["candidate"] = lambda payload: boss_scenarios.candidate(payload, 1)
        new = boss_start(auth, config)
        assert new.status_code == 202, new.text
        new_id = new.json()["id"]
        assert test_training.wait_run(auth, new_id).json()["status"] == "completed"
        assert answer(auth, new_id, config).status_code == 202
        assert wait_submission(auth, new_id)["awarded_points"] == 10
        assert evaluation_wait(auth, new_id)["status"] == "completed"
        assert client.get(f"/api/v1/boss/tasks/{new_id}", headers=auth).json()[
            "promotion_id"
        ]
    finally:
        options = json.loads(control.read_text())
        options["before_quality_settle"] = False
        control.write_text(json.dumps(options))
        test_training.stop_worker(process)


def test_bad_review_configuration_cannot_release_revalidation_or_replay_after_retest(
    pending, provider
):
    auth, config, requirement = pending
    identity = resolution.attempt(
        pending, provider, lambda payload: boss_scenarios.candidate(payload, 1)
    )
    provider["grading"] = lambda context: corrected(context)["grading"]
    resolution.finish(pending, identity)
    owner, sources = actual(identity)
    failed, _ = report_for(owner, config, failed=True, sources=sources)
    publish(failed)
    provider["review"] = resolution.passing_review
    review_start(auth, identity, config)
    assert review_wait(auth, identity)["decision"] == "corrected"
    assert access(auth)["revalidations"][0]["status"] == "required"
    retest, _ = report_for(
        owner, config, sources=sources, supersedes=failed.artifact_id
    )
    publish(retest)
    with Session(engine) as session:
        lock_owner(session, owner)
        run = session.get(TrainingRun, uuid.UUID(identity))
        mark_reviewed_promotion(session, run, session.get(ScoreReview, run.id))
        session.commit()
    still = access(auth)["revalidations"][0]
    assert (
        still["status"] == "required"
        and still["current_event_id"] == requirement["current_event_id"]
    )
