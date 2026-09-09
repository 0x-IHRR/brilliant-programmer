"""Pure candidate/version rules, not a natural-language understanding gate.

The future owner-authenticated adapter must persist versions and confirmation
with CAS, then pass the confirmed goal/focus into generation. Model output enters
through Analysis only; it cannot supply node identities or confirmation. These
rules do not generate, unlock, award, or reinterpret completion/evidence records.
"""

import uuid
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.capabilities.catalog import CATALOG, Catalog, EvidenceKey, Level

Kind = Literal["non_engineering", "clear", "broad", "clarify"]


class Goal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    target: EvidenceKey
    text: str
    focus: str

    @field_validator("text", "focus")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("goal and focus must be explicit")
        return value.strip()


class Analysis(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Kind
    message: str
    goals: tuple[Goal, ...] = ()
    recommended_index: int | None = None

    @model_validator(mode="after")
    def shape(self) -> Self:
        if not self.message.strip():
            raise ValueError("explain the proposed interpretation or clarification")
        count = len(self.goals)
        if self.kind in {"non_engineering", "clarify"}:
            if count or self.recommended_index is not None:
                raise ValueError("an unresolved topic cannot contain a startable goal")
        else:
            if (self.kind == "clear" and count != 1) or (
                self.kind == "broad" and not 3 <= count <= 5
            ):
                raise ValueError("clear needs one goal; a broad segment needs 3–5")
            if (
                self.recommended_index is None
                or not 0 <= self.recommended_index < count
            ):
                raise ValueError("recommend one explicit goal")
        return self


class Node(Goal):
    id: uuid.UUID


class Version(BaseModel):
    """Trusted stored snapshot, never a request/model response schema."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: uuid.UUID
    parent_id: uuid.UUID | None
    catalog_version: str
    input_text: str
    kind: Kind
    message: str
    nodes: tuple[Node, ...]
    recommended_id: uuid.UUID | None
    confirmed: bool = False


class StartSnapshot(Goal):
    version_id: uuid.UUID
    node_id: uuid.UUID
    catalog_version: str


def input_action(text: str) -> Literal["random", "analyze"]:
    # No keyword classifier: nonempty natural language still needs actual analysis.
    return "analyze" if text.strip() else "random"


def _level(target: EvidenceKey, catalog: Catalog) -> Level:
    for domain in catalog.domains:
        for capability in domain.capabilities:
            if (
                capability.id == target.capability_id
                and capability.background_id == target.background_id
            ):
                for level in capability.levels:
                    if level.difficulty == target.difficulty:
                        return level
    raise ValueError("target is not in the published catalog")


def propose(
    input_text: str,
    analysis: Analysis,
    *,
    previous: Version | None = None,
    expected_version: uuid.UUID | None = None,
    expand: bool = False,
    catalog: Catalog = CATALOG,
) -> Version:
    if (previous.id if previous else None) != expected_version:
        raise ValueError("topic version conflict; retain local input and reread")
    if input_action(input_text) == "random":
        raise ValueError("empty input offers random entry, not a topic plan")
    if expand and (
        not previous or previous.kind != "broad" or analysis.kind != "broad"
    ):
        raise ValueError("expansion adds one broad segment to an existing route")
    if expand and previous and previous.catalog_version != catalog.version:
        raise ValueError("replan against the current catalog before expanding")
    nodes = list(previous.nodes) if expand and previous else []
    used = {node.id for node in nodes}
    segment = []
    for goal in analysis.goals:
        _level(goal.target, catalog)
        # Reordering unchanged nodes preserves completion references. A changed
        # goal gets a new identity; the immutable older version retains its node.
        same = (
            next(
                (
                    node
                    for node in previous.nodes
                    if node.id not in used
                    and node.model_dump(exclude={"id"}) == goal.model_dump()
                ),
                None,
            )
            if previous
            else None
        )
        node = same or Node(id=uuid.uuid4(), **goal.model_dump())
        used.add(node.id)
        segment.append(node)
    return Version(
        id=uuid.uuid4(),
        parent_id=previous.id if previous else None,
        catalog_version=catalog.version,
        input_text=input_text,
        kind=analysis.kind,
        message=analysis.message,
        nodes=tuple(nodes + segment),
        recommended_id=segment[analysis.recommended_index].id
        if analysis.recommended_index is not None
        else None,
    )


def confirm(
    version: Version, expected_version: uuid.UUID, *, catalog: Catalog = CATALOG
) -> Version:
    if version.id != expected_version:
        raise ValueError("confirm the current candidate version explicitly")
    if version.catalog_version != catalog.version:
        raise ValueError("catalog changed; review a new candidate")
    if version.kind not in {"clear", "broad"}:
        raise ValueError("rewrite or clarify the topic before starting")
    return version.model_copy(update={"confirmed": True})


def start_snapshot(
    version: Version,
    expected_version: uuid.UUID,
    node_id: uuid.UUID,
    *,
    verified: set[EvidenceKey],
    opened: set[EvidenceKey] | None = None,
    opened_catalog_version: str | None = None,
    catalog: Catalog = CATALOG,
) -> StartSnapshot:
    if not version.confirmed or version.id != expected_version:
        raise ValueError("starting requires this confirmed version")
    if version.catalog_version != catalog.version:
        raise ValueError("catalog changed; review a new candidate")
    node = next((node for node in version.nodes if node.id == node_id), None)
    if node is None:
        raise ValueError("node does not belong to this version")
    level = _level(node.target, catalog)
    # Evidence and openings must come from the owner-authenticated server adapter.
    retained = opened_catalog_version == catalog.version and node.target in (
        opened or set()
    )
    if not retained and not level.satisfied_by(verified):
        raise ValueError("target prerequisites are not satisfied")
    return StartSnapshot(
        version_id=version.id,
        node_id=node.id,
        catalog_version=version.catalog_version,
        **node.model_dump(exclude={"id"}),
    )
