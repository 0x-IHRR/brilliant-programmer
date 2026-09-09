"""Owner-transaction settlement for accepted Boss rounds; no model calls."""

import json
import uuid

from sqlmodel import Session, col, select

from app.models import User
from app.training.boss import (
    BossCoverage,
    BossDecision,
    assess_first_boss,
    validate_boss_coverage,
)
from app.training.boss_models import (
    BossAttempt,
    BossDisposition,
    BossPromotion,
    BossRevalidation,
)
from app.training.boss_stages import (
    STAGES,
    BossStage,
    ObservationCoverage,
    ReleasedStage,
    StageDecision,
    assess_stage,
    parse_stage,
)
from app.training.comparison_service import coverage, qualification
from app.training.evaluation_models import Evaluation
from app.training.evaluation_schema import EvaluationInputs
from app.training.independent_models import IndependentWork
from app.training.models import TrainingRun
from app.training.review_models import ScoreReview
from app.training.review_service import effective_grading
from app.training.schema import Candidate, Source
from app.training.submission_models import Submission


def stage_for(session: Session, run_id: uuid.UUID) -> ReleasedStage | None:
    attempt = session.get(BossAttempt, run_id)
    return parse_stage(attempt.stage) if attempt else None


def decision_for(
    session: Session, run: TrainingRun, evaluation: Evaluation
) -> BossDecision | StageDecision | None:
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
        stage = parse_stage(attempt.stage)
        case = Candidate.model_validate(evaluation.case_snapshot)
        sources = [Source.model_validate(s) for s in evaluation.sources]
        inputs = EvaluationInputs.model_validate_json(json.dumps(evaluation.inputs))
        original = session.get(Submission, inputs.original.id)
        if (
            not original
            or original.run_id != run.id
            or original.kind != "original"
            or not accepted_lineage(session, attempt, run.user_id)
        ):
            raise ValueError("different accepted Boss lineage")
        grading_raw, excluded = effective_grading(session, run, evaluation)
        if excluded:
            return None
        novelty = qualification(work, case, sources, "")
        result: BossDecision | StageDecision
        if isinstance(stage, BossStage):
            result = assess_stage(
                stage=stage,
                launch_points=attempt.launch_points,
                current_level=owner.level,
                run_id=run.id,
                mode="independent",
                freeze_sequence=evaluation.frozen_sequence,
                case=case,
                sources=sources,
                inputs=inputs,
                grading_raw=grading_raw,
                novelty=novelty,
                deliveries=deliveries(session, run.id),
                key="",
                converted_sequence=run.converted_sequence,
                coverage=[
                    ObservationCoverage.model_validate(c) for c in coverage(work)
                ],
            )
        else:
            validate_boss_coverage(
                stage, case, [BossCoverage.model_validate(c) for c in coverage(work)]
            )
            result = assess_first_boss(
                stage=stage,
                launch_points=attempt.launch_points,
                current_level=owner.level,
                run_id=run.id,
                mode="independent",
                freeze_sequence=evaluation.frozen_sequence,
                case=case,
                sources=sources,
                inputs=inputs,
                grading_raw=grading_raw,
                novelty=novelty,
                deliveries=deliveries(session, run.id),
                key="",
                converted_sequence=run.converted_sequence,
            )
        disposition = session.get(BossDisposition, run.id)
        if result.promote_to and (
            attempt.revalidation_of
            or attempt.promotion_blocked
            or (disposition and disposition.outcome == "blocked_revalidation")
            or revalidations(session, run.user_id, pending_only=True)
        ):
            # Preserve the actual pass/fail evidence while exposing no promotion
            # proposal for a round whose advancement permission is blocked.
            return result.model_copy(update={"promote_to": None})
        return result
    except ValueError, KeyError, TypeError:
        return BossDecision(outcome="system_failure")


def accepted_lineage(
    session: Session, attempt: BossAttempt, owner_id: uuid.UUID
) -> bool:
    stage = parse_stage(attempt.stage)
    if attempt.revalidation_of is None:
        return attempt.launch_level == stage.from_level
    pending = session.get(BossRevalidation, attempt.revalidation_event_id)
    promotion = session.get(BossPromotion, attempt.revalidation_of)
    if (
        not pending
        or pending.kind != "required"
        or pending.promotion_id != attempt.revalidation_of
        or not promotion
        or promotion.user_id != owner_id
    ):
        return False
    original = session.get(BossAttempt, promotion.run_id)
    levels = ["小白程序员", *[item.from_level for item in STAGES]]
    return bool(
        original
        and original.stage == attempt.stage
        and promotion.to_level in levels
        and attempt.launch_level in levels
        and levels.index(attempt.launch_level) >= levels.index(promotion.to_level)
    )


def revalidations(
    session: Session, owner_id: uuid.UUID, *, pending_only: bool = False
) -> list[BossRevalidation]:
    rows = session.exec(
        select(BossRevalidation)
        .join(
            BossPromotion, col(BossPromotion.id) == col(BossRevalidation.promotion_id)
        )
        .where(BossPromotion.user_id == owner_id)
        .distinct(col(BossRevalidation.promotion_id))
        .order_by(
            col(BossRevalidation.promotion_id), col(BossRevalidation.sequence).desc()
        )
    ).all()
    return [row for row in rows if not pending_only or row.kind == "required"]


def append_revalidation(
    session: Session,
    promotion_id: uuid.UUID,
    *,
    review_run_id: uuid.UUID | None = None,
    resolved_run_id: uuid.UUID | None = None,
) -> None:
    # All callers hold the same User lock. The sequence retains each correction
    # and resolution; a later correction never erases an earlier successful check.
    latest = session.exec(
        select(BossRevalidation)
        .where(BossRevalidation.promotion_id == promotion_id)
        .order_by(col(BossRevalidation.sequence).desc())
    ).first()
    session.add(
        BossRevalidation(
            promotion_id=promotion_id,
            sequence=latest.sequence + 1 if latest else 1,
            kind="required" if review_run_id else "resolved",
            review_run_id=review_run_id,
            resolved_run_id=resolved_run_id,
        )
    )


def mark_reviewed_promotion(
    session: Session, run: TrainingRun, review: ScoreReview
) -> None:
    """Same User transaction as the validated review terminal; never lower a level."""
    if review.status != "completed" or review.decision != "corrected":
        return
    if session.exec(
        select(BossRevalidation.id).where(
            BossRevalidation.review_run_id == review.run_id
        )
    ).first():
        return
    promotion = session.exec(
        select(BossPromotion).where(BossPromotion.run_id == run.id)
    ).first()
    evaluation = session.get(Evaluation, run.id)
    attempt = session.get(BossAttempt, run.id)
    if not evaluation or not attempt:
        return
    if promotion:
        try:
            inputs = EvaluationInputs.model_validate_json(json.dumps(evaluation.inputs))
            stage = stage_for(session, run.id)
        except ValueError, TypeError, KeyError:
            return
        if (
            promotion.user_id != run.user_id
            or promotion.original_id != inputs.original.id
            or promotion.frozen_sequence != evaluation.frozen_sequence
            or not stage
            or (promotion.stage_version, promotion.from_level, promotion.to_level)
            != (stage.version, stage.from_level, stage.to_level)
        ):
            return
    elif attempt.revalidation_of:
        latest = next(
            (
                item
                for item in revalidations(session, run.user_id)
                if item.promotion_id == attempt.revalidation_of
            ),
            None,
        )
        if not latest or latest.kind != "resolved" or latest.resolved_run_id != run.id:
            return
        promotion = session.get(BossPromotion, latest.promotion_id)
    if not promotion:
        return
    result = decision_for(session, run, evaluation)
    if result and result.outcome in {"evidenced_fail", "unclear"}:
        append_revalidation(session, promotion.id, review_run_id=review.run_id)


def settle_boss(session: Session, run: TrainingRun, evaluation: Evaluation) -> None:
    """Caller holds User in this transaction, after the model permission closes."""
    attempt = session.get(BossAttempt, run.id)
    if (
        not attempt
        or session.get(ScoreReview, run.id) is not None
        or session.get(BossDisposition, run.id) is not None
    ):
        return
    # Freeze the blocked disposition even for a pending delivery: clearing an
    # unrelated restriction later cannot turn an old receipt into a new promotion.
    if not attempt.revalidation_of and (
        attempt.promotion_blocked
        or revalidations(session, run.user_id, pending_only=True)
    ):
        session.add(BossDisposition(run_id=run.id, outcome="blocked_revalidation"))
        return
    result = decision_for(session, run, evaluation)
    if not result:
        return
    if attempt.revalidation_of:
        pending = next(
            (
                item
                for item in revalidations(session, run.user_id, pending_only=True)
                if item.promotion_id == attempt.revalidation_of
            ),
            None,
        )
        if (
            pending
            and pending.id == attempt.revalidation_event_id
            and result.outcome == "independent_pass_candidate"
        ):
            append_revalidation(session, pending.promotion_id, resolved_run_id=run.id)
            session.add(BossDisposition(run_id=run.id, outcome="revalidated"))
        return
    if not result.promote_to:
        return
    owner = session.get(User, run.user_id, populate_existing=True)
    assert owner
    stage = stage_for(session, run.id)
    assert stage and stage.to_level and evaluation.frozen_sequence
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
    session.add(BossDisposition(run_id=run.id, outcome="promoted"))
    owner.level = stage.to_level
    session.add(owner)
