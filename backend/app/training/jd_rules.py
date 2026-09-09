"""JD source/route decisions, not semantic extraction or privacy certification.

Only the owner-authenticated adapter supplies document versions, evidence and
opened units. Model candidates cannot select a job, confirm, or supply node IDs.
Persistence/CAS, actual content inspection and disclosure remain adapter duties.
"""

import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.capabilities.catalog import CATALOG, Catalog, EvidenceKey
from app.capabilities.evidence import EvidenceMap
from app.training.topic_rules import (
    Goal,
    Node,
    StartSnapshot,
    Version,
    _level,
    confirm,
    start_snapshot,
)


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Document(Frozen):
    id: uuid.UUID
    text: str = Field(min_length=1)


class Quote(Frozen):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1)

    def check(self, document: Document) -> None:
        if (
            self.end <= self.start
            or document.text[self.start : self.end] != self.text
            or self.end > len(document.text)
        ):
            raise ValueError("quotation must match the exact original span")


class Requirement(Frozen):
    quote: Quote
    basis: Literal["explicit", "inferred"]
    explanation: str = Field(min_length=1)
    # Unknown/unsupported background stays unresolved, not a fabricated catalog key.
    goal: Goal | None


class Role(Frozen):
    name: str = Field(min_length=1)
    quote: Quote
    requirements: tuple[Requirement, ...] = Field(min_length=1)


class Analysis(Frozen):
    kind: Literal["roles", "no_requirements", "clarify"]
    message: str = Field(min_length=1)
    roles: tuple[Role, ...] = ()

    @model_validator(mode="after")
    def shape(self) -> Self:
        if (self.kind == "roles") != bool(self.roles):
            raise ValueError("unresolved JD asks for input, not a definite route")
        return self


class Mapping(Frozen):
    node_id: uuid.UUID
    requirement: Requirement


class Route(Frozen):
    document: Document
    role_name: str
    role_quote: Quote
    requirements: tuple[Requirement, ...]
    mappings: tuple[Mapping, ...]
    route: Version


def propose(
    document: Document,
    analysis: Analysis,
    *,
    selected_role: int | None = None,
    previous: Route | None = None,
    expected_version: uuid.UUID | None = None,
    catalog: Catalog = CATALOG,
) -> Route:
    if (previous.route.id if previous else None) != expected_version:
        raise ValueError("JD route version conflict; retain local input")
    if analysis.kind != "roles":
        raise ValueError("supplement or clarify the job requirements first")
    if selected_role is None:
        if len(analysis.roles) != 1:
            raise ValueError("select one job before building its route")
        selected_role = 0
    if not 0 <= selected_role < len(analysis.roles):
        raise ValueError("unknown selected job")
    # Validate all claims shown to the user, not only those eventually selected.
    for role in analysis.roles:
        role.quote.check(document)
        for requirement in role.requirements:
            requirement.quote.check(document)
            if requirement.goal:
                _level(requirement.goal.target, catalog)
    role = analysis.roles[selected_role]
    same_role = bool(
        previous
        and previous.document == document
        and previous.role_name == role.name
        and previous.role_quote == role.quote
        and previous.route.catalog_version == catalog.version
    )
    nodes: list[Node] = []
    mappings = []
    used = set()
    for requirement in role.requirements:
        if requirement.goal is None:
            continue
        old = (
            next(
                (
                    mapping
                    for mapping in previous.mappings
                    if mapping.node_id not in used
                    and mapping.requirement == requirement
                ),
                None,
            )
            if same_role and previous
            else None
        )
        identity = old.node_id if old else uuid.uuid4()
        used.add(identity)
        nodes.append(Node(id=identity, **requirement.goal.model_dump()))
        mappings.append(Mapping(node_id=identity, requirement=requirement))
    route = Version(
        id=uuid.uuid4(),
        parent_id=previous.route.id if previous else None,
        catalog_version=catalog.version,
        input_text=role.name,
        kind="clear" if len(nodes) == 1 else "broad" if nodes else "clarify",
        message=analysis.message,
        nodes=tuple(nodes),
        recommended_id=nodes[0].id if nodes else None,
    )
    return Route(
        document=document,
        role_name=role.name,
        role_quote=role.quote,
        requirements=role.requirements,
        mappings=tuple(mappings),
        route=route,
    )


def confirm_route(
    route: Route, expected_version: uuid.UUID, *, catalog: Catalog = CATALOG
) -> Route:
    return route.model_copy(
        update={"route": confirm(route.route, expected_version, catalog=catalog)}
    )


class EvidenceView(Frozen):
    target: EvidenceKey | None
    status: Literal["unknown", "unverified", "verified", "needs_consolidation"]
    streak: int | None
    latest_verified_at: datetime | None = None
    original_ids: tuple[uuid.UUID, ...] = ()


def evidence_for(
    requirement: Requirement, evidence: EvidenceMap | None
) -> EvidenceView:
    target = requirement.goal.target if requirement.goal else None
    if target is None or evidence is None:
        return EvidenceView(target=target, status="unknown", streak=None)
    state = next((state for state in evidence.states if state.target == target), None)
    if state is None:
        return EvidenceView(target=target, status="unverified", streak=0)
    return EvidenceView(
        target=target,
        status=state.status,
        streak=state.streak,
        latest_verified_at=state.latest_verified_at,
        original_ids=tuple(
            dict.fromkeys(h.evidence.original_id for h in state.history if h.counted)
        ),
    )


class Simulation(StartSnapshot):
    document_version: uuid.UUID
    requirement: Requirement
    simulation_label: Literal["教学模拟"] = "教学模拟"


class ConfirmedJDGoal(Goal):
    """Minimal provenance retained in each complete-history comparison request."""

    requirement_quote: str
    basis: Literal["explicit", "inferred"]
    simulation_label: Literal["教学模拟"]


def start(
    route: Route,
    expected_version: uuid.UUID,
    node_id: uuid.UUID,
    *,
    verified: set[EvidenceKey],
    opened: set[EvidenceKey] | None = None,
    opened_catalog_version: str | None = None,
    catalog: Catalog = CATALOG,
) -> Simulation:
    snapshot = start_snapshot(
        route.route,
        expected_version,
        node_id,
        verified=verified,
        opened=opened,
        opened_catalog_version=opened_catalog_version,
        catalog=catalog,
    )
    requirement = next(
        mapping.requirement for mapping in route.mappings if mapping.node_id == node_id
    )
    return Simulation(
        **snapshot.model_dump(),
        document_version=route.document.id,
        requirement=requirement,
    )


def analysis_input(document: Document) -> dict[str, str]:
    # Full JD is necessary for extraction; no profile, previous answers or evidence.
    # The actual caller must disclose this and apply the existing secret boundary.
    return {"jd_text": document.text}


def generation_input(snapshot: Simulation) -> dict[str, object]:
    # A selected quotation may still contain personal data. This is an allowlist,
    # NOT automatic redaction; inspect/disclose the actual outbound fields later.
    return {
        "target": snapshot.target.model_dump(),
        "goal": snapshot.text,
        "focus": snapshot.focus,
        "requirement_quote": snapshot.requirement.quote.text,
        "basis": snapshot.requirement.basis,
        "simulation_label": snapshot.simulation_label,
    }
