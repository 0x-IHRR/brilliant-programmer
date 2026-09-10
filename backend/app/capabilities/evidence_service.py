"""Owner-locked, read-only projection from persisted frozen server facts.

Full history plus cumulative novelty comparisons are revalidated on each read.
Keep this auditable projection until measured latency warrants an incremental
projection; do not trim history or impose a learning cap to hide its cost.
"""

import json
import uuid
from typing import cast

from sqlmodel import Session, col, select

from app.capabilities.catalog import EvidenceKey
from app.capabilities.evidence import Evidence, EvidenceMap, project
from app.capabilities.evidence_models import OriginalOrder
from app.quality.models import QualityDisposition
from app.quality.rules import QualityStatus
from app.training.boss import BossCoverage, validate_boss_coverage
from app.training.boss_service import stage_for
from app.training.boss_stages import (
    BossStage,
    ObservationCoverage,
    qualified_item,
    validate_stage_coverage,
)
from app.training.comparison_service import coverage as work_coverage
from app.training.comparison_service import qualification as assess_work
from app.training.evaluation_models import Evaluation
from app.training.evaluation_schema import EvaluationInputs, validate_grading
from app.training.independent_models import IndependentObservation, IndependentWork
from app.training.independent_novelty import (
    case_digest,
)
from app.training.models import TrainingRun
from app.training.review_models import ScoreReview
from app.training.review_service import effective_grading
from app.training.schema import Candidate, Source
from app.training.submission_models import Submission


def read_evidence(session: Session, user_id: uuid.UUID) -> EvidenceMap:
    records: list[Evidence] = []
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
        facet_eligible = False
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
                assessment = assess_work(work, case, sources, "")
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
                facet_eligible = qualified
                # Preserve the ORIGINAL observation's help/novelty qualification.
                # Select the reviewed witnesses BEFORE Boss per-facet grounding;
                # replacing a projected facet afterward would grant unsupported proof.
                if session.get(ScoreReview, run.id):
                    raw, excluded = effective_grading(session, run, evaluation)
                    if excluded:
                        outcome, qualified = excluded, False
                    elif raw:
                        grading = validate_grading(raw, case, sources, inputs, "")
                        revised = {item.conclusion for item in grading.items}
                        if qualified:
                            outcome = (
                                "evidenced_fail"
                                if "evidenced_fail" in revised
                                else "unclear"
                                if "unclear" in revised
                                else "independent_pass_candidate"
                            )
                digest = case_digest(case)
                judgments = [item.judgment_id for item in grading.items]
            except ValueError, KeyError, TypeError:
                outcome = "evidence_unavailable"
        review = session.get(ScoreReview, run.id)
        if review and review.decision in {"pending", "disputed"}:
            outcome, qualified = review.decision, False
        quality = session.get(
            QualityDisposition,
            (
                run.id,
                "review" if review and review.status == "completed" else "original",
            ),
        )
        original_quality = session.get(QualityDisposition, (run.id, "original"))
        if (quality and quality.status == "failed") or (
            original_quality and original_quality.status == "failed"
        ):
            outcome, qualified, facet_eligible = "quality_failed", False, False
        from app.deletion.service import unavailable

        erased = unavailable(session, user_id, run.id)
        if erased:
            outcome, qualified, facet_eligible = "evidence_unavailable", False, False
            digest, judgments = None, []
        record = Evidence(
            grading_quality=cast(QualityStatus, quality.status)
            if quality
            else "unverified",
            quality_report_id=quality.report_id if quality else None,
            review_id=review.request_id if review else None,
            review_decision=review.decision if review else None,
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
        stage = stage_for(session, run.id)
        if stage and erased:
            records.extend(
                record.model_copy(update={"kind": "boss", "target": mandatory.target})
                for mandatory in stage.mandatory
            )
            continue
        if stage and observation and (qualified or (review and facet_eligible)):
            try:
                assert work and work.novelty
                facets = []
                if isinstance(stage, BossStage):
                    facets = [
                        ObservationCoverage.model_validate(c)
                        for c in work_coverage(work)
                    ]
                    validate_stage_coverage(stage, case, facets)
                else:
                    validate_boss_coverage(
                        stage,
                        case,
                        [BossCoverage.model_validate(c) for c in work_coverage(work)],
                    )
                by_id = {item.judgment_id: item for item in grading.items}
                for mandatory in stage.mandatory:
                    item = by_id[mandatory.judgment_id]
                    records.append(
                        record.model_copy(
                            update={
                                "kind": "boss",
                                "target": mandatory.target,
                                "judgment_ids": [mandatory.judgment_id],
                                "outcome": (
                                    outcome
                                    if review
                                    and review.decision in {"pending", "disputed"}
                                    else "independent_pass_candidate"
                                    if item.conclusion == "pass"
                                    and (
                                        not isinstance(stage, BossStage)
                                        or qualified_item(item, facets)
                                    )
                                    else "unclear"
                                    if item.conclusion == "pass"
                                    else item.conclusion
                                ),
                            }
                        )
                    )
                continue
            except ValueError, KeyError, TypeError:
                record = record.model_copy(
                    update={
                        "outcome": "evidence_unavailable",
                        "qualified_novelty": False,
                    }
                )
        records.append(record)
    return project(records)
