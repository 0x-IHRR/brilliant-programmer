"""Project route adapters; source snapshots never follow later acquisition."""

import json
import uuid

from fastapi import HTTPException
from sqlmodel import Session

from app.project.schema import ProjectMap, Snapshot
from app.project.training_models import ProjectInput, ProjectTopic, ProjectVersion
from app.project.training_rules import ModuleGoal, ProjectRoute, propose
from app.training.schema import Strict, Text
from app.training.topic_analysis import Inspection
from app.training.topic_models import Topic, TopicJob
from app.training.topic_rules import Goal, Version
from app.training.topic_service import save_version


class ModuleAnalysis(Strict):
    goals: tuple[ModuleGoal, ...]
    message: Text


def is_project(session: Session, topic_id: uuid.UUID) -> bool:
    return session.get(ProjectTopic, topic_id) is not None


def route(
    session: Session, topic: Topic, identity: uuid.UUID | None
) -> ProjectRoute | None:
    if identity is None:
        return None
    row = session.get(ProjectVersion, identity)
    source = session.get(ProjectInput, row.input_id) if row else None
    if not row or not source or source.topic_id != topic.id:
        raise HTTPException(404, "项目路线版本不属于此记录")
    return ProjectRoute.model_validate_json(json.dumps(row.snapshot))


def save(
    session: Session, topic: Topic, value: ProjectRoute, input_id: uuid.UUID
) -> None:
    save_version(session, topic, value.route)
    session.flush()
    session.add(
        ProjectVersion(
            version_id=value.route.id,
            input_id=input_id,
            snapshot=value.model_dump(mode="json"),
        )
    )


def accept(session: Session, topic: Topic, item: TopicJob, raw: str) -> None:
    source = session.get(ProjectInput, item.id)
    assert source and source.topic_id == topic.id
    if item.stage == "inspect":
        inspection = Inspection.model_validate_json(raw)
        if not inspection.accepted or not inspection.explanation.strip():
            raise ValueError("project route content inspection rejected")
    analysis = (
        ModuleAnalysis.model_validate_json(raw)
        if item.stage == "analyze"
        else ModuleAnalysis.model_validate_json(json.dumps(item.candidate))
    )
    value = propose(
        source.project_run_id,
        Snapshot.model_validate(source.snapshot),
        ProjectMap.model_validate(source.project_map),
        analysis.goals,
        key="",
        previous=route(session, topic, item.expected_version),
        expected_version=item.expected_version,
    )
    value = value.model_copy(
        update={"route": value.route.model_copy(update={"message": analysis.message})}
    )
    if item.stage == "analyze":
        item.candidate = analysis.model_dump(mode="json")
        item.stage = "inspect"
    else:
        save(session, topic, value, source.id)
        item.result_id = value.route.id
        item.status, item.code, item.message = (
            "completed",
            "ok",
            "项目模块路线已核对；请确认目标，尚未生成题目",
        )


def save_edit(
    session: Session, topic: Topic, previous_id: uuid.UUID, value: Version
) -> None:
    previous = route(session, topic, previous_id)
    row = session.get(ProjectVersion, previous_id)
    assert previous and row
    by_id = {binding.node_id: binding for binding in previous.bindings}
    bindings = []
    for index, node in enumerate(value.nodes):
        binding = by_id.get(node.id, previous.bindings[index])
        bindings.append(
            binding.model_copy(
                update={
                    "node_id": node.id,
                    "proposal": binding.proposal.model_copy(
                        update={
                            "goal": Goal.model_validate(node.model_dump(exclude={"id"}))
                        }
                    ),
                }
            )
        )
    # Validate nested updates before persistence; identity only changes through Topic CAS.
    updated = ProjectRoute.model_validate(
        {
            **previous.model_dump(),
            "route": value.model_dump(),
            "bindings": tuple(b.model_dump() for b in bindings),
        }
    )
    save(session, topic, updated, row.input_id)


def analysis_context(source: ProjectInput) -> dict[str, object]:
    snapshot = Snapshot.model_validate(source.snapshot)
    mapped = ProjectMap.model_validate(source.project_map)
    paths = {f.subject for f in mapped.confirmed if f.kind == "module"}
    return {
        "repository": snapshot.repository.model_dump(mode="json"),
        "confirmed_modules": sorted(paths),
        "fragments": [
            f.model_dump(mode="json") for f in snapshot.fragments if f.path in paths
        ],
        "missing": mapped.missing,
    }
