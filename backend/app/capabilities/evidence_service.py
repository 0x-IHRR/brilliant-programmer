"""Owner-locked, read-only projection from persisted frozen server facts.

Full history plus cumulative novelty comparisons are revalidated on each read.
Keep this auditable projection until measured latency warrants an incremental
projection; do not trim history or impose a learning cap to hide its cost.
"""

import json
import uuid

from sqlmodel import Session, col, select

from app.capabilities.catalog import EvidenceKey
from app.capabilities.evidence import Evidence, EvidenceMap, project
from app.capabilities.evidence_models import OriginalOrder
from app.training.evaluation_models import Evaluation
from app.training.evaluation_schema import EvaluationInputs, validate_grading
from app.training.independent_models import IndependentObservation, IndependentWork
from app.training.independent_novelty import (
    ScenarioComparison,
    assess_novelty,
    case_digest,
)
from app.training.models import TrainingRun
from app.training.schema import Candidate, Source
from app.training.submission_models import Submission


def read_evidence(session: Session, user_id: uuid.UUID) -> EvidenceMap:
    records = []
    orders = session.exec(
        select(OriginalOrder)
        .where(OriginalOrder.user_id == user_id)
        .order_by(col(OriginalOrder.position))
    ).all()
    for order in orders:
        original = session.get(Submission, order.original_id)
        if not original:
            continue
        run = session.get(TrainingRun, original.run_id)
        assert run is not None and run.user_id == user_id
        observation = session.exec(
            select(IndependentObservation)
            .where(
                IndependentObservation.original_id == original.id,
                IndependentObservation.run_id == run.id,
            )
            .order_by(col(IndependentObservation.sequence).desc())
        ).first()
        outcome = "practice" if run.launch_mode == "practice" else "awaiting_evaluation"
        qualified = False
        digest = None
        judgments: list[str] = []
        if observation:
            outcome = observation.outcome
            try:
                evaluation = session.get(Evaluation, run.id)
                work = session.get(IndependentWork, run.id)
                if (
                    not evaluation
                    or not work
                    or not work.novelty
                    or evaluation.status != "completed"
                ):
                    raise ValueError("unavailable frozen evaluation")
                case = Candidate.model_validate(evaluation.case_snapshot)
                inputs = EvaluationInputs.model_validate_json(
                    json.dumps(evaluation.inputs)
                )
                if (
                    inputs.original.id != original.id
                    or observation.frozen_sequence != evaluation.frozen_sequence
                    or observation.target != case.target.model_dump()
                    or observation.case_digest != case_digest(case)
                ):
                    raise ValueError("unbound observation")
                sources = [Source.model_validate(s) for s in evaluation.sources]
                assessment = assess_novelty(
                    case,
                    sources,
                    {
                        uuid.UUID(h["run_id"]): Candidate.model_validate_json(h["case"])
                        for h in work.history
                    },
                    [
                        ScenarioComparison.model_validate_json(json.dumps(c))
                        for c in work.novelty["comparisons"]["comparisons"]
                    ],
                    "",
                )
                grading = validate_grading(
                    json.dumps(evaluation.result), case, sources, inputs, ""
                )
                conclusions = {item.conclusion for item in grading.items}
                expected = (
                    "evidenced_fail"
                    if "evidenced_fail" in conclusions
                    else "unclear"
                    if "unclear" in conclusions
                    else "independent_pass_candidate"
                )
                qualified = (
                    assessment.status == "novelty_candidate" and outcome == expected
                )
                digest = case_digest(case)
                judgments = [item.judgment_id for item in grading.items]
            except ValueError, KeyError, TypeError:
                outcome = "evidence_unavailable"
        records.append(
            Evidence(
                original_id=original.id,
                run_id=run.id,
                order=order.position,
                submitted_at=order.submitted_at,
                order_source="legacy_created_at_uuid"
                if order.source == "legacy_created_at_uuid"
                else "user_locked",
                target=EvidenceKey.model_validate(run.target),
                observation_id=observation.id if observation else None,
                observation_sequence=observation.sequence if observation else None,
                frozen_sequence=observation.frozen_sequence if observation else None,
                outcome=outcome,
                qualified_novelty=qualified,
                case_digest=digest,
                judgment_ids=judgments,
            )
        )
    return project(records)
