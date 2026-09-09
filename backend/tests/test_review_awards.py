"""Seeded historical missing-award recovery; not an ordinary completion shortcut."""

import copy
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from sqlmodel import Session, select

from app.capabilities.evidence_models import OriginalOrder
from app.core.db import engine
from app.training.evaluation_models import Evaluation
from app.training.evaluation_schema import EVALUATION_RULE, evaluation_inputs
from app.training.models import TrainingRun
from app.training.review_models import ReviewAward, ScoreReview
from app.training.review_service import points
from app.training.review_worker import context, settle
from app.training.submission_models import PracticeAward
from tests.test_evaluation_schema import example
from tests.test_model_config import account, save
from tests.test_review_rules import opinion
from tests.test_reviews import start


@pytest.mark.parametrize("completed,previous", [(True, 0), (True, 10), (False, 0)])
def test_owner_transaction_only_pays_missing_total_and_never_creates_completion(
    completed, previous
):
    case, sources, original, grading = example("choice")
    owner, auth = account()
    config = save(auth).json()
    now = datetime.now(UTC)
    with Session(engine) as session:
        run = TrainingRun(
            id=original.run_id,
            user_id=owner,
            config_version=uuid.UUID(config["version"]),
            destination=config["service_url"],
            model_id=config["model_id"],
            target=case.target.model_dump(),
            selection={"catalog_version": case.catalog_version},
            sources=[s.model_dump() for s in sources],
            candidate=case.model_dump(),
            status="completed",
            formal_submitted_at=now if completed else None,
        )
        original.status = "completed" if completed else "needs_supplement"
        original.sequence = 1
        session.add(run)
        session.flush()
        session.add(original)
        session.flush()
        session.add(
            OriginalOrder(
                original_id=original.id, user_id=owner, position=1, submitted_at=now
            )
        )
        old = copy.deepcopy(grading)
        old["items"][0].update(conclusion="unclear", gap="原评分待确认")
        session.add(
            Evaluation(
                run_id=run.id,
                inputs=evaluation_inputs([original]).model_dump(mode="json"),
                case_snapshot=case.model_dump(),
                sources=[s.model_dump() for s in sources],
                rule_version=EVALUATION_RULE,
                config_version=run.config_version,
                destination=run.destination,
                model_id=run.model_id,
                status="completed",
                frozen_sequence=3,
                frozen_at=now,
                result=old,
            )
        )
        if previous:
            session.add(
                PracticeAward(run_id=run.id, user_id=owner, submission_id=original.id)
            )
        session.commit()
        identity = run.id
        session.refresh(original)
    start(auth, str(identity), config)
    with Session(engine) as session:
        item = session.get(ScoreReview, identity)
        job = item.queue_job_id
        assert context(item)["inputs"]["original"]
    raw = opinion(grading)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: settle(identity, job, raw), range(2)))
    assert sorted(results) == [False, True]
    with Session(engine) as session:
        assert points(session, owner, identity) == (10 if completed else 0)
        assert bool(session.get(TrainingRun, identity).formal_submitted_at) == completed
        assert len(
            session.exec(
                select(ReviewAward).where(ReviewAward.run_id == identity)
            ).all()
        ) == (completed and not previous)
        assert session.get(Evaluation, identity).result == old
    if completed and not previous:
        # A later normal settlement must see the restored total, not issue ten
        # again merely because its original PracticeAward row was absent.
        from app.training.submission_models import Submission
        from app.training.submission_schema import Relevance
        from app.training.submission_worker import settle as settle_submission

        with Session(engine) as session:
            later = Submission(
                run_id=identity,
                original_id=original.id,
                kind="supplement",
                sequence=4,
                answers=original.answers,
                input_hash=str(uuid.uuid4()),
                config_version=uuid.UUID(config["version"]),
                destination=config["service_url"],
                model_id=config["model_id"],
                status="checking",
            )
            session.add(later)
            session.commit()
            later_id = later.id
        assert settle_submission(
            later_id,
            Relevance.model_validate(
                {
                    "items": [
                        {"judgment_id": j.id, "status": "related"}
                        for j in case.judgments
                    ]
                }
            ),
        )
        with Session(engine) as session:
            assert points(session, owner, identity) == 10
            assert session.get(PracticeAward, identity) is None
    # Queue has not been consumed in this seed-only test; terminal duplicate will exit.
    import procrastinate

    from app.training.queue import DSN

    with procrastinate.App(
        connector=procrastinate.SyncPsycopgConnector(conninfo=DSN)
    ).open() as app:
        app.job_manager.cancel_job_by_id(job, abort=True)
