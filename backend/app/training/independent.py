"""Pure independent-check decisions over server facts, not public request claims.

Callers must own/lock the round, bind the frozen case and input lineage, and allocate
all sequences using next_event. This module performs no delivery, persistence,
award or level update. Existing rounds must never be passed to launch_mode again.
"""

import uuid
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.training.concept_delivery import DeliveryFact
from app.training.concept_schema import Direction
from app.training.evaluation_schema import EvaluationInputs, validate_grading
from app.training.independent_novelty import NoveltyAssessment, case_digest
from app.training.schema import Candidate, Source, Strict, validate_candidate

Mode = Literal["practice", "independent"]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

DIRECTIONAL_CONFIRMATION = "继续后本题转为练习，不计入独立验证；已有修为不变"
UNCERTAIN_CONFIRMATION = (
    "不确定是否含解题提示；查看后本题按练习记录，不计入独立验证，已有修为不变"
)


def launch_mode(
    *, run_id: uuid.UUID, requested: bool, origin_id: uuid.UUID | None
) -> Mode:
    """Every ordinary entry defaults to practice; requesting a check creates a round."""
    if not requested:
        return "practice"
    if origin_id == run_id:
        raise ValueError("independent check requires a new round")
    return "independent"


class Confirmation(Strict):
    """Server-recorded consent to this exact inspected publication, not delivery."""

    run_id: uuid.UUID
    help_id: uuid.UUID
    content_hash: Digest
    direction: Direction
    sequence: int = Field(gt=0)


class PublicationPermission(Strict):
    allowed: bool
    prompt: str | None


def publication_permission(
    *,
    run_id: uuid.UUID,
    help_id: uuid.UUID,
    content_hash: str,
    sequence: int,
    mode: Mode,
    direction: Direction,
    confirmation: Confirmation | None = None,
) -> PublicationPermission:
    """Call before releasing any content bytes; does not convert or mark seen.

    mode is the current mode, not retrospective eligibility of a frozen answer.
    A post-freeze publication may change future handling, never the frozen answer.
    """
    if sequence <= 0:
        raise ValueError("publication needs server sequence")
    if mode == "practice" or direction == "neutral":
        return PublicationPermission(allowed=True, prompt=None)
    allowed = bool(
        confirmation
        and confirmation.run_id == run_id
        and confirmation.help_id == help_id
        and confirmation.content_hash == content_hash
        and confirmation.direction == direction
        and confirmation.sequence < sequence
    )
    return PublicationPermission(
        allowed=allowed,
        prompt=None
        if allowed
        else (
            DIRECTIONAL_CONFIRMATION
            if direction == "directional"
            else UNCERTAIN_CONFIRMATION
        ),
    )


class OrderedDelivery(DeliveryFact):
    """Adapter for HelpDelivery rows; receipt authentication stays in the route."""

    id: uuid.UUID
    run_id: uuid.UUID
    exposure_sequence: int = Field(gt=0)
    attempt_id: uuid.UUID | None = None
    content_hash: Digest

    @model_validator(mode="after")
    def ordered(self) -> OrderedDelivery:
        if self.exposure_sequence > self.sequence or (
            self.attempt_id is None and self.exposure_sequence != self.sequence
        ):
            raise ValueError("invalid exposure order")
        return self


def resolved_deliveries(
    run_id: uuid.UUID, deliveries: list[OrderedDelivery]
) -> list[OrderedDelivery]:
    """Resolve an unknown attempt only with a matching append-only observation.

    The server must pass the complete round history, not a filtered latest row.
    A receipt's later sequence cannot move the original exposure past the freeze.
    """
    by_id = {event.id: event for event in deliveries}
    if (
        len(by_id) != len(deliveries)
        or len({e.sequence for e in deliveries}) != len(deliveries)
        or any(e.run_id != run_id for e in deliveries)
    ):
        raise ValueError("invalid delivery history")
    resolved: dict[uuid.UUID, OrderedDelivery] = {}
    for event in deliveries:
        if event.attempt_id is None:
            continue
        attempt = by_id.get(event.attempt_id)
        if (
            attempt is None
            or attempt.attempt_id is not None
            or attempt.status != "delivery_unknown"
            or attempt.id in resolved
            or event.sequence <= attempt.sequence
            or event.exposure_sequence != attempt.sequence
            or event.help_id != attempt.help_id
            or event.content_hash != attempt.content_hash
        ):
            raise ValueError("invalid delivery receipt lineage")
        resolved[attempt.id] = event
    return [resolved.get(e.id, e) for e in deliveries if e.attempt_id is None]


def independence_at_freeze(
    *,
    run_id: uuid.UUID,
    mode: Mode,
    freeze_sequence: int,
    deliveries: list[OrderedDelivery],
    converted_sequence: int | None = None,
) -> Literal["practice", "independent", "pending_delivery"]:
    """Retrospective qualification of frozen inputs, without rewriting any input.

    mode is immutable launch mode. A separately ordered voluntary conversion is
    irreversible for this round, but cannot revoke an already frozen answer.
    Actual directional/uncertain delivery also converts even with missing consent:
    a publication bug must never manufacture independent evidence.
    """
    if freeze_sequence <= 0 or (
        converted_sequence is not None
        and (converted_sequence <= 0 or converted_sequence == freeze_sequence)
    ):
        raise ValueError("invalid freeze/conversion sequence")
    events = resolved_deliveries(run_id, deliveries)
    if any(
        e.sequence == freeze_sequence or e.exposure_sequence == freeze_sequence
        for e in deliveries
    ):
        raise ValueError("events must have distinct server sequences")
    if mode == "practice" or (
        converted_sequence is not None and converted_sequence < freeze_sequence
    ):
        return "practice"
    before = [e for e in events if e.exposure_sequence < freeze_sequence]
    if any(
        e.status in {"delivered", "partial"} and e.direction != "neutral"
        for e in before
    ):
        return "practice"
    if any(e.status == "delivery_unknown" for e in before):
        return "pending_delivery"
    return "independent"


Outcome = Literal[
    "practice",
    "pending_delivery",
    "no_qualified_case",
    "invalid_case",
    "system_failure",
    "unclear",
    "evidenced_fail",
    "independent_pass_candidate",
]


def frozen_outcome(
    *,
    run_id: uuid.UUID,
    mode: Mode,
    freeze_sequence: int,
    case: Candidate,
    sources: list[Source],
    inputs: EvaluationInputs,
    grading_raw: str | None,
    novelty: NoveltyAssessment,
    deliveries: list[OrderedDelivery],
    key: str,
    converted_sequence: int | None = None,
) -> Outcome:
    """Proposal for a frozen evaluation, never a direct level/award mutation.

    Inputs come from evaluation_inputs and the immutable Evaluation snapshot,
    novelty from the server comparison of complete history. Public clients cannot
    submit these facts. A pass remains a model-interpreted evidence candidate;
    this function neither certifies semantic accuracy nor updates user levels.
    Unknown history exposures must also be reconciled before assigning novelty.
    """
    snapshots = [inputs.original] + (
        [inputs.clarification] if inputs.clarification else []
    )
    if (
        any(s.sequence <= 0 or s.sequence >= freeze_sequence for s in snapshots)
        or len({s.id for s in snapshots}) != len(snapshots)
        or (
            inputs.clarification is not None
            and (
                not inputs.clarification_used
                or inputs.clarification.sequence <= inputs.original.sequence
            )
        )
    ):
        raise ValueError("invalid input freeze order")
    independence = independence_at_freeze(
        run_id=run_id,
        mode=mode,
        freeze_sequence=freeze_sequence,
        deliveries=deliveries,
        converted_sequence=converted_sequence,
    )
    if independence != "independent":
        return independence
    try:
        validate_candidate(case.model_dump_json(), case.target, sources, key)
    except ValueError:
        return "invalid_case"
    if novelty.status != "novelty_candidate" or novelty.case_digest != case_digest(
        case
    ):
        return "no_qualified_case"
    if grading_raw is None:
        return "system_failure"
    try:
        grading = validate_grading(grading_raw, case, sources, inputs, key)
    except ValueError:
        return "system_failure"
    conclusions = {item.conclusion for item in grading.items}
    if "evidenced_fail" in conclusions:
        return "evidenced_fail"
    if "unclear" in conclusions:
        return "unclear"
    return "independent_pass_candidate"
