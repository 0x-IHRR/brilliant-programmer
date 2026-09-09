"""Pure decisions for server-owned review snapshots; no model or persistence IO.

Caller must serialize acceptance by evaluation identity, commit pending before
acknowledging it, and settle against the latest owner-locked history/award total.
These checks validate witnesses, not the model's natural-language interpretation.
"""

import json
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.capabilities.evidence import Evidence, EvidenceMap, project
from app.model_config.output import check_output
from app.training.evaluation_schema import (
    EvaluationInputs,
    GradingCandidate,
    validate_grading,
)
from app.training.schema import Candidate, Source, Strict, Text
from app.training.submission_models import REWARD_POINTS, REWARD_RULE


class FrozenReview(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    # Evaluation currently has the run ID as its primary key.
    run_id: uuid.UUID
    original_id: uuid.UUID
    original_order: int = Field(gt=0)
    frozen_sequence: int = Field(gt=0)
    evaluation_rule: str
    # Canonical strings prevent nested mutation of the accepted snapshot.
    case_json: str
    sources_json: str
    inputs_json: str
    grading_json: str


def freeze(
    run_id: uuid.UUID,
    original_order: int,
    frozen_sequence: int,
    evaluation_rule: str,
    case: Candidate,
    sources: list[Source],
    inputs: EvaluationInputs,
    grading: GradingCandidate,
) -> FrozenReview:
    """Arguments come from persisted Evaluation/OriginalOrder, never request fields."""
    if not evaluation_rule or frozen_sequence <= max(
        inputs.original.sequence,
        inputs.clarification.sequence if inputs.clarification else 0,
    ):
        raise ValueError("unfrozen evaluation")
    return FrozenReview(
        run_id=run_id,
        original_id=inputs.original.id,
        original_order=original_order,
        frozen_sequence=frozen_sequence,
        evaluation_rule=evaluation_rule,
        case_json=case.model_dump_json(),
        sources_json=json.dumps(
            [s.model_dump(mode="json") for s in sources], sort_keys=True
        ),
        inputs_json=inputs.model_dump_json(),
        grading_json=grading.model_dump_json(),
    )


class Opinion(Strict):
    decision: Literal["upheld", "corrected", "disputed"]
    explanation: Text
    grading: GradingCandidate | None


class Review(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    request_id: uuid.UUID
    snapshot: FrozenReview
    # Transport errors leave pending; they are not a disputed terminal opinion.
    status: Literal["pending", "upheld", "corrected", "disputed"] = "pending"
    opinion_json: str | None = None


def accept(
    request_id: uuid.UUID, snapshot: FrozenReview, existing: Review | None
) -> Review:
    if existing is not None:
        if existing.request_id != request_id or existing.snapshot != snapshot:
            raise ValueError("evaluation review already accepted")
        return existing
    return Review(request_id=request_id, snapshot=snapshot)


def conclude(review: Review, raw: str, key: str) -> Review:
    check_output(raw, key)
    opinion = Opinion.model_validate_json(raw)
    canonical = opinion.model_dump_json()
    if review.status != "pending":
        if review.opinion_json == canonical:
            return review
        raise ValueError("review already concluded")
    if opinion.decision == "disputed":
        if opinion.grading is not None:
            raise ValueError("dispute cannot install a grading conclusion")
    else:
        if opinion.grading is None:
            raise ValueError("missing review witnesses")
        snapshot = review.snapshot
        grading = validate_grading(
            opinion.grading.model_dump_json(),
            Candidate.model_validate_json(snapshot.case_json),
            [Source.model_validate(s) for s in json.loads(snapshot.sources_json)],
            EvaluationInputs.model_validate_json(snapshot.inputs_json),
            key,
        )
        before = {
            i.judgment_id: i.conclusion
            for i in GradingCandidate.model_validate_json(snapshot.grading_json).items
        }
        after = {i.judgment_id: i.conclusion for i in grading.items}
        if any(value == "unclear" for value in after.values()):
            raise ValueError("unresolved review must remain disputed")
        if (before == after) != (opinion.decision == "upheld"):
            raise ValueError("review decision contradicts grading changes")
    return review.model_copy(
        update={"status": opinion.decision, "opinion_json": canonical}
    )


def recalculate(records: list[Evidence], reviews: list[Review]) -> EvidenceMap:
    """Use all current records, including answers received while review was pending.

    No opened-unit, level or points argument: this cannot restore an old account
    snapshot. The caller supplies novelty/qualification from the existing adapter.
    """
    by_original: dict[uuid.UUID, Review] = {}
    for entry in reviews:
        if entry.snapshot.original_id in by_original:
            raise ValueError("duplicate review interpretation")
        by_original[entry.snapshot.original_id] = entry
    revised = []
    for record in records:
        review = by_original.get(record.original_id)
        if review is None:
            revised.append(record)
            continue
        snapshot = review.snapshot
        if (record.run_id, record.order, record.frozen_sequence) != (
            snapshot.run_id,
            snapshot.original_order,
            snapshot.frozen_sequence,
        ):
            raise ValueError("review does not belong to original evidence")
        outcome: str
        case = Candidate.model_validate_json(snapshot.case_json)
        if record.kind == "ordinary" and record.target != case.target:
            raise ValueError("review cannot change the original evidence key")
        if review.status in {"pending", "disputed"}:
            outcome = review.status
        elif record.outcome == "practice" or not record.qualified_novelty:
            outcome = record.outcome
        else:
            assert review.opinion_json
            grading = Opinion.model_validate_json(review.opinion_json).grading
            assert grading
            items = {item.judgment_id: item.conclusion for item in grading.items}
            if not record.judgment_ids or not set(record.judgment_ids) <= items.keys():
                raise ValueError("review missing assessed judgment")
            outcomes = {items[identity] for identity in record.judgment_ids}
            outcome = (
                "evidenced_fail"
                if "evidenced_fail" in outcomes
                else "independent_pass_candidate"
            )
        revised.append(record.model_copy(update={"outcome": outcome}))
    return project(revised)


def reward_difference(
    review: Review, *, completed: bool, rule_version: str, paid: int
) -> int:
    """Caller sums initial awards AND earlier supplements under the settlement lock."""
    if paid < 0 or rule_version != REWARD_RULE:
        raise ValueError("unknown completion rule or invalid cumulative payment")
    if review.status != "corrected":
        return 0
    due = REWARD_POINTS if completed else 0
    return max(0, due - paid)
