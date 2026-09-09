"""Owner-transaction settlement for accepted Boss rounds; no model calls."""

import json
import uuid

from sqlmodel import Session, select

from app.models import User
from app.training.boss import (
    BossCoverage,
    BossDecision,
    FirstStage,
    assess_first_boss,
    validate_boss_coverage,
)
from app.training.boss_models import BossAttempt, BossPromotion
from app.training.evaluation_models import Evaluation
from app.training.evaluation_schema import EvaluationInputs
from app.training.independent_models import IndependentWork
from app.training.independent_novelty import ScenarioComparison, assess_novelty
from app.training.models import TrainingRun
from app.training.schema import Candidate, Source
from app.training.submission_models import Submission


def stage_for(session: Session, run_id: uuid.UUID) -> FirstStage | None:
    attempt = session.get(BossAttempt, run_id)
    return (
        FirstStage.model_validate_json(json.dumps(attempt.stage)) if attempt else None
    )


def decision_for(
    session: Session, run: TrainingRun, evaluation: Evaluation
) -> BossDecision | None:
    from app.training.independent_service import deliveries

    attempt = session.get(BossAttempt, run.id)
    if (
        not attempt
        or not evaluation.frozen_sequence
        or evaluation.status != "completed"
    ):
        return None
    owner = session.get(User, run.user_id, populate_existing=True)
    assert owner
    work = session.get(IndependentWork, run.id)
    try:
        if not work or not work.novelty or run.launch_mode != "independent":
            raise ValueError("missing Boss qualification")
        stage = FirstStage.model_validate_json(json.dumps(attempt.stage))
        case = Candidate.model_validate(evaluation.case_snapshot)
        sources = [Source.model_validate(s) for s in evaluation.sources]
        inputs = EvaluationInputs.model_validate_json(json.dumps(evaluation.inputs))
        original = session.get(Submission, inputs.original.id)
        if (
            not original
            or original.run_id != run.id
            or original.kind != "original"
            or attempt.launch_level != stage.from_level
        ):
            raise ValueError("different accepted Boss lineage")
        parsed = work.novelty["comparisons"]
        validate_boss_coverage(
            stage,
            case,
            [BossCoverage.model_validate(c) for c in parsed["boss_coverage"]],
        )
        novelty = assess_novelty(
            case,
            sources,
            {
                uuid.UUID(h["run_id"]): Candidate.model_validate_json(h["case"])
                for h in work.history
            },
            [
                ScenarioComparison.model_validate_json(json.dumps(c))
                for c in parsed["comparisons"]
            ],
            "",
        )
        return assess_first_boss(
            stage=stage,
            launch_points=attempt.launch_points,
            current_level=owner.level,
            run_id=run.id,
            mode="independent",
            freeze_sequence=evaluation.frozen_sequence,
            case=case,
            sources=sources,
            inputs=inputs,
            grading_raw=json.dumps(evaluation.result) if evaluation.result else None,
            novelty=novelty,
            deliveries=deliveries(session, run.id),
            key="",
            converted_sequence=run.converted_sequence,
        )
    except ValueError, KeyError, TypeError:
        return BossDecision(outcome="system_failure")


def settle_boss(session: Session, run: TrainingRun, evaluation: Evaluation) -> None:
    """Caller holds User lock in THIS transaction, after releasing HTTP permission.

    #28 revalidation does not exist yet; no fabricated pending state is stored.
    Existing first promotion and actual current level independently prevent replay.
    """
    result = decision_for(session, run, evaluation)
    if not result or not result.promote_to:
        return
    owner = session.get(User, run.user_id, populate_existing=True)
    assert owner
    stage = stage_for(session, run.id)
    assert stage and evaluation.frozen_sequence
    previous = session.exec(
        select(BossPromotion).where(
            BossPromotion.user_id == owner.id,
            BossPromotion.from_level == stage.from_level,
        )
    ).first()
    if previous or owner.level != stage.from_level:
        return
    inputs = EvaluationInputs.model_validate_json(json.dumps(evaluation.inputs))
    session.add(
        BossPromotion(
            user_id=owner.id,
            run_id=run.id,
            original_id=inputs.original.id,
            frozen_sequence=evaluation.frozen_sequence,
            stage_version=stage.version,
            from_level=stage.from_level,
            to_level=stage.to_level,
        )
    )
    owner.level = stage.to_level
    session.add(owner)
