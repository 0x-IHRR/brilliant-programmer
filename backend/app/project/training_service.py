"""Project route adapters; source snapshots never follow later acquisition."""

import json
import uuid

from fastapi import HTTPException
from sqlmodel import Session, select

from app.project.schema import ProjectMap, Repository, Snapshot, same_scope
from app.project.training_models import (
    ProjectInput,
    ProjectRouteFamily,
    ProjectRouteUpdate,
    ProjectTopic,
    ProjectVersion,
)
from app.project.training_rules import ModuleGoal, ProjectRoute, propose
from app.training.schema import Strict, Text
from app.training.topic_analysis import Inspection
from app.training.topic_models import Topic, TopicJob, TopicVersion
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
    previous = route(session, topic, item.expected_version)
    if previous is None and source.previous_version_id:
        old_version = session.get(TopicVersion, source.previous_version_id)
        assert old_version
        old_topic = session.get(Topic, old_version.topic_id)
        assert old_topic and old_topic.user_id == topic.user_id
        previous = route(session, old_topic, old_version.id)
    value = propose(
        source.project_run_id,
        Snapshot.model_validate(source.snapshot),
        ProjectMap.model_validate(source.project_map),
        analysis.goals,
        key="",
        previous=previous,
        expected_version=previous.route.id if previous else None,
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


def family(session: Session, topic: Topic) -> ProjectRouteFamily | None:
    update = session.get(ProjectRouteUpdate, topic.id)
    return session.get(ProjectRouteFamily, update.root_topic_id if update else topic.id)


def family_topics(session: Session, topic: Topic) -> list[uuid.UUID]:
    group = family(session, topic)
    if not group:
        return [topic.id]
    return [
        group.root_topic_id,
        *session.exec(
            select(ProjectRouteUpdate.topic_id).where(
                ProjectRouteUpdate.root_topic_id == group.root_topic_id
            )
        ).all(),
    ]


def active_route(
    session: Session, topic: Topic
) -> tuple[uuid.UUID, ProjectRoute] | None:
    group = family(session, topic)
    identity = group.active_version_id if group else topic.active_id
    if identity is None:
        return None
    version_row = session.get(TopicVersion, identity)
    assert version_row
    owner = session.get(Topic, version_row.topic_id)
    assert owner and owner.user_id == topic.user_id
    value = route(session, owner, identity)
    assert value
    return owner.id, value


def link_update(
    session: Session,
    topic: Topic,
    previous_id: uuid.UUID,
    repository: Repository,
    expected_active: uuid.UUID | None,
) -> None:
    row = session.get(TopicVersion, previous_id)
    previous_topic = session.get(Topic, row.topic_id) if row else None
    if not previous_topic or previous_topic.user_id != topic.user_id:
        raise HTTPException(404, "前路线版本不存在")
    previous = route(session, previous_topic, previous_id)
    if not previous or not same_scope(previous.repository, repository):
        raise HTTPException(409, "前路线不属于同一仓库与完整读取范围")
    group = family(session, previous_topic)
    active = group.active_version_id if group else previous_topic.active_id
    if (
        previous_topic.active_id != previous_id
        or active != previous_id
        or expected_active != active
    ):
        raise HTTPException(409, "前路线须为仍生效的已确认版本；请重读，旧当前路线保留")
    if not group:
        group = ProjectRouteFamily(
            root_topic_id=previous_topic.id, active_version_id=active
        )
        session.add(group)
        session.flush()
    session.add(
        ProjectRouteUpdate(
            topic_id=topic.id,
            root_topic_id=group.root_topic_id,
            previous_version_id=previous_id,
        )
    )


def activate(
    session: Session,
    topic: Topic,
    version_id: uuid.UUID,
    expected_active: uuid.UUID | None,
) -> None:
    """User lock serializes confirmations across updated, immutable Topic records."""
    group = family(session, topic)
    active = group.active_version_id if group else topic.active_id
    if active == version_id and topic.active_id == version_id:
        return
    if expected_active != active:
        raise HTTPException(409, "当前项目路线已变化；请重读比较，未替换已确认路线")
    if not group:
        group = ProjectRouteFamily(root_topic_id=topic.id)
    group.active_version_id = version_id
    session.add(group)
