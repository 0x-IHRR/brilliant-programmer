"""Pure project-route provenance, not runtime facts or semantic certification.

The owner-authenticated adapter supplies the saved map/snapshot and persists CAS
versions. No fetching, execution, model calls, rewards or unlock writes occur here.
"""

import hashlib
import json
import uuid
from pathlib import PurePosixPath
from typing import Literal
from urllib.parse import quote

from pydantic import Field

from app.capabilities.catalog import CATALOG, Catalog, EvidenceKey
from app.model_config.output import check_output
from app.project.schema import (
    Location,
    ProjectMap,
    Repository,
    Sha,
    Snapshot,
    validate_map,
)
from app.training.schema import Candidate, Source, Strict, Text, validate_candidate
from app.training.topic_rules import (
    Goal,
    Node,
    StartSnapshot,
    Version,
    _level,
    confirm,
    start_snapshot,
)


class ModuleGoal(Strict):
    module_path: Text
    goal: Goal
    evidence: tuple[Location, ...]
    missing: tuple[Text, ...] = ()


class CodeReference(Strict):
    location: Location
    blob: Sha
    source: Source


class Binding(Strict):
    node_id: uuid.UUID
    proposal: ModuleGoal
    references: tuple[CodeReference, ...]


class ProjectRoute(Strict):
    project_run_id: uuid.UUID
    repository: Repository
    # Map limitations stay visible even if this selected module has usable text.
    map_missing: tuple[str, ...]
    route: Version
    bindings: tuple[Binding, ...]


def bind_reference(snapshot: Snapshot, location: Location, key: str) -> CodeReference:
    path = PurePosixPath(location.path)
    if path.is_absolute() or ".." in path.parts or str(path) != location.path:
        raise ValueError("invalid repository-relative path")
    # Reuse the same exact line/quote gate used by the map, including later slices.
    validate_map(
        json.dumps(
            {
                "findings": [
                    {
                        "kind": "module",
                        "subject": location.path,
                        "relation": "source reference",
                        "target": location.path,
                        "evidence": [location.model_dump()],
                    }
                ],
                "missing": [],
            }
        ),
        snapshot.fragments,
        key,
    )
    matches = [
        f
        for f in snapshot.fragments
        if f.path == location.path
        and f.start <= location.start <= location.end <= f.end
    ]
    blobs = {f.blob for f in matches}
    if len(blobs) != 1 or any(
        f.end > f.total_lines or len(f.text.splitlines()) != f.end - f.start + 1
        for f in matches
    ):
        raise ValueError("ambiguous or incomplete fragment identity")
    blob = next(iter(blobs))
    entries = [e for e in snapshot.entries if e.path == location.path]
    if (
        len(entries) != 1
        or entries[0].sha != blob
        or entries[0].kind != "blob"
        or entries[0].mode not in {"100644", "100755"}
        or location.path in snapshot.excluded
    ):
        raise ValueError("fragment does not belong to the saved repository tree")
    repository = snapshot.repository
    url = (
        f"https://github.com/{quote(repository.owner, safe='')}/"
        f"{quote(repository.name, safe='')}/blob/{repository.commit}/"
        f"{quote(location.path, safe='/')}#L{location.start}-L{location.end}"
    )
    identity = hashlib.sha256(f"{url}:{blob}:{location.quote}".encode()).hexdigest()
    return CodeReference(
        location=location,
        blob=blob,
        source=Source(
            id="project-" + identity,
            url=url,
            version=repository.commit,
            locator=f"{location.path}:{location.start}-{location.end}; blob {blob}",
            text=location.quote,
        ),
    )


def propose(
    project_run_id: uuid.UUID,
    snapshot: Snapshot,
    project_map: ProjectMap,
    goals: tuple[ModuleGoal, ...],
    *,
    key: str,
    previous: ProjectRoute | None = None,
    expected_version: uuid.UUID | None = None,
    catalog: Catalog = CATALOG,
) -> ProjectRoute:
    check_output(json.dumps([g.model_dump(mode="json") for g in goals]), key)
    if (previous.route.id if previous else None) != expected_version:
        raise ValueError("project route version conflict; retain local input")
    same = bool(
        previous
        and previous.project_run_id == project_run_id
        and previous.repository == snapshot.repository
        and previous.route.catalog_version == catalog.version
    )
    modules = {f.subject for f in project_map.confirmed if f.kind == "module"}
    nodes, bindings = [], []
    used: set[uuid.UUID] = set()
    for goal in goals:
        _level(goal.goal.target, catalog)
        if goal.module_path not in modules:
            raise ValueError("module has no confirmed read evidence")
        if not goal.evidence and not goal.missing:
            raise ValueError("list missing module evidence before proposing generation")
        refs = tuple(bind_reference(snapshot, loc, key) for loc in goal.evidence)
        if refs and not any(r.location.path == goal.module_path for r in refs):
            raise ValueError("selected module itself has no retained source")
        old = (
            next(
                (
                    b
                    for b in previous.bindings
                    if b.node_id not in used
                    and b.proposal == goal
                    and b.references == refs
                ),
                None,
            )
            if same and previous
            else None
        )
        identity = old.node_id if old else uuid.uuid4()
        used.add(identity)
        nodes.append(Node(id=identity, **goal.goal.model_dump()))
        bindings.append(Binding(node_id=identity, proposal=goal, references=refs))
    route = Version(
        id=uuid.uuid4(),
        parent_id=previous.route.id if previous else None,
        catalog_version=catalog.version,
        input_text=f"{snapshot.repository.owner}/{snapshot.repository.name}",
        kind="clear" if len(nodes) == 1 else "broad" if nodes else "clarify",
        message="模块顺序是学习建议；新入口仍按真实能力前置核验，源码引用不证明运行事实。",
        nodes=tuple(nodes),
        recommended_id=nodes[0].id if nodes else None,
    )
    return ProjectRoute(
        project_run_id=project_run_id,
        repository=snapshot.repository,
        map_missing=tuple(project_map.missing)
        + (() if modules else ("尚无已核实模块，不能据此生成项目案例",))
        + tuple(f"{path}: {reason}" for path, reason in snapshot.excluded.items())
        + tuple(
            f"{location.path}:{location.start}-{location.end}: model relationship unverified"
            for finding in project_map.unverified
            for location in finding.evidence
        )
        + (() if snapshot.listing_complete else ("repository listing incomplete",)),
        route=route,
        bindings=tuple(bindings),
    )


def confirm_route(
    route: ProjectRoute, expected_version: uuid.UUID, *, catalog: Catalog = CATALOG
) -> ProjectRoute:
    return route.model_copy(
        update={"route": confirm(route.route, expected_version, catalog=catalog)}
    )


class Selection(Strict):
    project_run_id: uuid.UUID
    repository: Repository
    goal: StartSnapshot
    module_path: Text
    references: tuple[CodeReference, ...]
    simulation_label: Literal["教学模拟"] = "教学模拟"


def start(
    route: ProjectRoute,
    expected_version: uuid.UUID,
    node_id: uuid.UUID,
    *,
    verified: set[EvidenceKey],
    opened: set[EvidenceKey] | None = None,
    opened_catalog_version: str | None = None,
    catalog: Catalog = CATALOG,
) -> Selection:
    goal = start_snapshot(
        route.route,
        expected_version,
        node_id,
        verified=verified,
        opened=opened,
        opened_catalog_version=opened_catalog_version,
        catalog=catalog,
    )
    binding = next(b for b in route.bindings if b.node_id == node_id)
    if binding.proposal.missing or not binding.references:
        raise ValueError(
            "missing module evidence: " + "; ".join(binding.proposal.missing)
        )
    return Selection(
        project_run_id=route.project_run_id,
        repository=route.repository,
        goal=goal,
        module_path=binding.proposal.module_path,
        references=binding.references,
    )


def generation_input(selection: Selection, key: str) -> dict[str, object]:
    # The real sender must inspect/disclose these fields, not the entire repository
    # or account history. Reference hashes identify sources; they never prove novelty.
    value: dict[str, object] = {
        "goal": selection.goal.model_dump(
            mode="json", include={"target", "text", "focus"}
        ),
        "module": selection.module_path,
        "sources": [r.source.model_dump(mode="json") for r in selection.references],
        "simulation_label": selection.simulation_label,
    }
    check_output(json.dumps(value), key)
    return value


class MaterialOrigin(Strict):
    # Origin of the displayed material text, not proof of derived facts or runtime behavior.
    evidence_id: Text
    kind: Literal["code_excerpt", "teaching_assumption", "synthetic_log"]


class ProjectCandidate(Strict):
    case: Candidate
    materials: tuple[MaterialOrigin, ...] = Field(min_length=1)


def validate_project_candidate(
    raw: str, selection: Selection, key: str
) -> ProjectCandidate:
    """Structural source binding only; an actual content inspector must still review
    the goal, hypothetical facts, source sufficiency and Variation's causal effect.
    Full-history assess_novelty remains mandatory for independent qualification.
    """
    check_output(raw, key)
    value = ProjectCandidate.model_validate_json(raw)
    case = validate_candidate(
        value.case.model_dump_json(),
        selection.goal.target,
        [r.source for r in selection.references],
        key,
    )
    origins = {m.evidence_id: m.kind for m in value.materials}
    if len(origins) != len(value.materials) or set(origins) != {
        e.id for e in case.evidence
    }:
        raise ValueError("every teaching material needs an explicit origin label")
    for item in case.evidence:
        if origins[item.id] == "code_excerpt" and not any(
            item.text == r.source.text
            and any(c.source_id == r.source.id for c in item.citations)
            for r in selection.references
        ):
            raise ValueError("claimed code excerpt is not the frozen source text")
    return value
