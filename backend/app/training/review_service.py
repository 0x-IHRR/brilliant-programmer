"""Review interpretation before the shared qualification/facet projection."""

import json
import uuid

from fastapi import HTTPException
from sqlalchemy import func
from sqlmodel import Session, select

from app.capabilities.evidence_models import OriginalOrder
from app.training.evaluation_models import Evaluation
from app.training.evaluation_schema import EvaluationInputs, GradingCandidate
from app.training.models import TrainingRun
from app.training.review_models import ReviewAward, ScoreReview
from app.training.review_rules import (
    FrozenReview,
    Opinion,
    Review,
    conclude,
    freeze,
    reward_difference,
)
from app.training.schema import Candidate, Source
from app.training.submission_models import PracticeAward, Submission


def domain(item: ScoreReview) -> Review:
    return Review.model_validate(
        {
            "request_id": item.request_id,
            "snapshot": item.snapshot,
            "status": item.decision,
            "opinion_json": json.dumps(item.opinion) if item.opinion else None,
        }
    )


def snapshot_for(
    session: Session, run: TrainingRun, evaluation: Evaluation
) -> FrozenReview:
    if (
        evaluation.status != "completed"
        or not evaluation.frozen_sequence
        or not evaluation.result
    ):
        raise HTTPException(409, "本次评分尚未冻结完成，不能受理评分复核")
    inputs = EvaluationInputs.model_validate_json(json.dumps(evaluation.inputs))
    original = session.get(Submission, inputs.original.id)
    order = session.get(OriginalOrder, inputs.original.id)
    if (
        not original
        or original.run_id != run.id
        or original.kind != "original"
        or original.practice_help_id
        or not order
        or order.user_id != run.user_id
    ):
        raise HTTPException(409, "原评分身份不完整，未受理复核")
    return freeze(
        run.id,
        order.position,
        evaluation.frozen_sequence,
        evaluation.rule_version,
        Candidate.model_validate(evaluation.case_snapshot),
        [Source.model_validate(s) for s in evaluation.sources],
        inputs,
        GradingCandidate.model_validate(evaluation.result),
    )


def effective_grading(
    session: Session, run: TrainingRun, evaluation: Evaluation
) -> tuple[str | None, str | None]:
    """Never replace the original Evaluation or treat a review as independent proof.

    Caller must still run qualification, frozen_outcome and each Boss facet against
    these effective witnesses; late help receipts cannot reinstall the original grade.
    """
    item = session.get(ScoreReview, run.id)
    if not item:
        return json.dumps(evaluation.result) if evaluation.result else None, None
    try:
        snapshot = snapshot_for(session, run, evaluation)
    except HTTPException:
        return None, "evidence_unavailable"
    if domain(item).snapshot != snapshot:
        return None, "evidence_unavailable"
    if item.decision in {"pending", "disputed"}:
        return None, item.decision
    if not item.opinion:
        return None, "evidence_unavailable"
    initial = Review(request_id=item.request_id, snapshot=domain(item).snapshot)
    checked = conclude(initial, json.dumps(item.opinion), "")
    opinion = Opinion.model_validate_json(checked.opinion_json or "{}")
    return opinion.grading.model_dump_json() if opinion.grading else None, None


def points(
    session: Session, user_id: uuid.UUID, run_id: uuid.UUID | None = None
) -> int:
    total = 0
    for model in (PracticeAward, ReviewAward):
        query = select(func.coalesce(func.sum(model.points), 0)).where(
            model.user_id == user_id
        )
        if run_id is not None:
            query = query.where(model.run_id == run_id)
        total += int(session.exec(query).one())
    return total


def settle_difference(session: Session, run: TrainingRun, item: ScoreReview) -> int:
    """Same User-locked transaction as opinion; no completion/level/opening writes."""
    # Ordinary full submission OR a genuinely completed guided practice can finish
    # this round. A grade change, stored draft, or merely published case cannot.
    completed = run.formal_submitted_at is not None or bool(
        session.exec(
            select(Submission.id).where(
                Submission.run_id == run.id, Submission.status == "completed"
            )
        ).first()
    )
    delta = reward_difference(
        domain(item),
        completed=completed,
        rule_version=run.completion_rule_version,
        paid=points(session, run.user_id, run.id),
    )
    if delta and not session.get(ReviewAward, run.id):
        session.add(
            ReviewAward(
                run_id=run.id,
                user_id=run.user_id,
                points=delta,
                rule_version=run.completion_rule_version,
            )
        )
    return delta
