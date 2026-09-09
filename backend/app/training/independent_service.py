"""Round-locked adapters; never expose private novelty comparisons."""

import json
import uuid

from sqlmodel import Session, col, select

from app.training.concept_models import HelpDelivery
from app.training.evaluation_models import Evaluation
from app.training.evaluation_schema import EvaluationInputs
from app.training.events import next_event
from app.training.independent import (
    OrderedDelivery,
    frozen_outcome,
    resolved_deliveries,
)
from app.training.independent_models import IndependentObservation, IndependentWork
from app.training.independent_novelty import NoveltyAssessment, case_digest
from app.training.models import TrainingRun
from app.training.schema import Candidate, Source

HISTORY_BYTES = 96 * 1024


def deliveries(session: Session, run_id: uuid.UUID) -> list[OrderedDelivery]:
    return [
        OrderedDelivery.model_validate(
            row.model_dump(
                include={
                    "id",
                    "run_id",
                    "help_id",
                    "sequence",
                    "exposure_sequence",
                    "attempt_id",
                    "status",
                    "direction",
                    "delivered_text",
                    "content_hash",
                    "occurred_at",
                }
            )
        )
        for row in session.exec(
            select(HelpDelivery).where(HelpDelivery.run_id == run_id)
        ).all()
    ]


def capture_history(session: Session, run: TrainingRun) -> dict[uuid.UUID, Candidate]:
    """Complete user history, never latest-N or hash-only semantic exclusion.

    Legacy public cases conservatively count as seen. No private generated case
    counts as seen. Unknown help must be reconciled before another check starts.
    Caller holds User through capture/acceptance, serializing new publications.
    """
    rows = session.exec(
        select(TrainingRun)
        .where(
            TrainingRun.user_id == run.user_id,
            TrainingRun.id != run.id,
            col(TrainingRun.candidate).is_not(None),
        )
        .order_by(col(TrainingRun.created_at), col(TrainingRun.id))
    ).all()
    result = {}
    for row in rows:
        # SQL JSON null is not SQL NULL. A stopped/failed unpublished round
        # has no seen case and must not poison later direct prerequisite checks.
        if row.candidate is None:
            continue
        if any(
            e.status == "delivery_unknown"
            for e in resolved_deliveries(row.id, deliveries(session, row.id))
        ):
            raise ValueError("unresolved_history_delivery")
        case = Candidate.model_validate(row.candidate)
        result[row.id] = case
    return result


def history(session: Session, run: TrainingRun) -> list[dict[str, str]]:
    """Legacy checkpoint reader; new tasks use a bounded reference snapshot."""
    result = [
        {"run_id": str(identity), "case": case.model_dump_json()}
        for identity, case in capture_history(session, run).items()
    ]
    if len(json.dumps(result).encode()) > HISTORY_BYTES:
        raise ValueError("history_exceeds_budget")
    return result


def record_frozen(session: Session, run: TrainingRun, evaluation: Evaluation) -> None:
    """Called under User and round event order after settlement/receipt, no model.

    Earlier observations stay immutable; resolving an unknown appends a new fact
    about the same frozen input. Post-freeze help cannot change that outcome.
    """
    if (
        run.launch_mode != "independent"
        or not evaluation.frozen_sequence
        or evaluation.status != "completed"
    ):
        return
    work = session.get(IndependentWork, run.id)
    if not work or not work.novelty:
        return
    inputs = EvaluationInputs.model_validate_json(json.dumps(evaluation.inputs))
    case = Candidate.model_validate(evaluation.case_snapshot)
    outcome = frozen_outcome(
        run_id=run.id,
        mode="independent",
        freeze_sequence=evaluation.frozen_sequence,
        case=case,
        sources=[Source.model_validate(s) for s in evaluation.sources],
        inputs=inputs,
        grading_raw=json.dumps(evaluation.result) if evaluation.result else None,
        novelty=NoveltyAssessment.model_validate(work.novelty["assessment"]),
        deliveries=deliveries(session, run.id),
        key="",
        converted_sequence=run.converted_sequence,
    )
    from app.quality.rules import Binding
    from app.quality.service import freeze, status

    current, _ = status(
        session,
        Binding(
            user_id=run.user_id,
            config_version=evaluation.config_version,
            destination=evaluation.destination,
            model_id=evaluation.model_id,
            evaluation_rule=evaluation.rule_version,
        ),
        [Source.model_validate(s) for s in evaluation.sources],
    )
    # A delivery still being resolved has not yet established independent evidence.
    # Known failure freezes denial now; a later retest cannot revive this round.
    if current == "failed" or outcome != "pending_delivery":
        freeze(session, run, evaluation)
    from app.training.boss_service import settle_boss

    settle_boss(session, run, evaluation)
    latest = session.exec(
        select(IndependentObservation)
        .where(
            IndependentObservation.run_id == run.id,
        )
        .order_by(col(IndependentObservation.sequence).desc())
    ).first()
    if latest and latest.outcome == outcome:
        return
    session.add(
        IndependentObservation(
            run_id=run.id,
            sequence=next_event(session, run.id),
            frozen_sequence=evaluation.frozen_sequence,
            original_id=inputs.original.id,
            case_digest=case_digest(case),
            target=case.target.model_dump(),
            outcome=outcome,
        )
    )
