"""Server-observed delivery facts; no eligibility mutation or client receipt trust.

The persistence boundary must allocate sequence under the same lock/order as input
freezing. HTTP response creation/sending alone is not confirmed delivery. Record an
unknown outcome separately; never overwrite earlier evidence with a later receipt.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.training.concept_schema import (
    ConceptContent,
    ContentReview,
    Direction,
    classify_content,
)
from app.training.schema import Strict

DeliveryStatus = Literal[
    "not_delivered", "delivered", "partial", "delivery_unknown", "failed", "cancelled"
]


class DeliveryFact(Strict):
    help_id: uuid.UUID
    sequence: int = Field(gt=0)
    occurred_at: datetime
    status: DeliveryStatus
    delivered_text: str
    direction: Direction | None
    classification_version: Literal["concept-inspection-v1"] = "concept-inspection-v1"

    @model_validator(mode="after")
    def coherent(self) -> DeliveryFact:
        known_delivery = self.status in {"delivered", "partial"}
        if known_delivery != bool(self.delivered_text) or known_delivery != (
            self.direction is not None
        ):
            raise ValueError("delivery evidence does not match status")
        if self.occurred_at.tzinfo is None:
            raise ValueError("server time must have timezone")
        return self


def observe_delivery(
    *,
    help_id: uuid.UUID,
    sequence: int,
    occurred_at: datetime,
    content: ConceptContent | None = None,
    review: ContentReview | None = None,
    status: DeliveryStatus,
    observed_text: str,
) -> DeliveryFact:
    """Build an immutable fact from server evidence, never from public request fields.

    Generated/confirmed-but-not-delivered content stays private. A caller must
    persist each fact, including uncertainty, alongside the exact generated content
    and inspection. This helper does not claim a network or database commit occurred.
    """
    if status not in {"delivered", "partial"}:
        return DeliveryFact(
            help_id=help_id,
            sequence=sequence,
            occurred_at=occurred_at,
            status=status,
            delivered_text=observed_text,
            direction=None,
        )
    if content is None or review is None:
        raise ValueError("known delivery requires inspected content")
    direction = classify_content(content, review)
    full_text = "\n\n".join(content.sections().values())
    if status == "delivered" and observed_text != full_text:
        raise ValueError("complete delivery needs exact content")
    if status == "partial":
        if (
            not observed_text
            or observed_text == full_text
            or not full_text.startswith(observed_text)
        ):
            raise ValueError("partial delivery needs actual content prefix")
        directions: list[Direction] = []
        offset = 0
        # Review ordering is untrusted; use the delivered content order.
        by_section = {item.section: item for item in review.sections}
        for name, section in content.sections().items():
            if len(observed_text) <= offset:
                break
            item = by_section[name]
            complete_section = len(observed_text) >= offset + len(section)
            if not complete_section:
                directions.append("uncertain")
            elif item.accuracy == "uncertain":
                directions.append("uncertain")
            else:
                directions.append(item.direction)
            offset += len(section) + 2
        direction = (
            "directional"
            if "directional" in directions
            else "uncertain"
            if "uncertain" in directions
            else "neutral"
        )
    return DeliveryFact(
        help_id=help_id,
        sequence=sequence,
        occurred_at=occurred_at,
        status=status,
        delivered_text=observed_text,
        direction=direction if status in {"delivered", "partial"} else None,
    )
