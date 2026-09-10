"""Owner-scoped project routes over the existing version/queue lifecycle."""

import uuid

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict
from sqlmodel import Session, col, select

from app.api.deps import SessionDep
from app.model_config.models import ModelConfig
from app.model_config.service import lock_owner
from app.project.models import ProjectRun
from app.project.schema import ProjectMap, Repository, Snapshot
from app.project.training_models import ProjectInput, ProjectTopic
from app.project.training_rules import ProjectRoute
from app.project.training_service import (
    active_route,
    family,
    family_topics,
    link_update,
    route,
)
from app.training.projection import read_snapshot
from app.training.routes import VerifiedUser
from app.training.topic_models import Topic, TopicJob
from app.training.topic_service import compare, owned
from app.training.topics import TopicPublic, _public, enqueue

router = APIRouter(prefix="/project-training", tags=["projecttraining"])


class ProjectTrainingPublic(BaseModel):
    topic: TopicPublic
    project_run_id: uuid.UUID
    current: ProjectRoute | None
    active: ProjectRoute | None
    active_topic_id: uuid.UUID | None
    family_id: uuid.UUID
    source_repository: Repository
    semantic_reliability: str = "unverified"


class AnalyzeProject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID
    topic_id: uuid.UUID
    project_run_id: uuid.UUID
    expected_version: uuid.UUID | None = None
    previous_version_id: uuid.UUID | None = None
    expected_active_version: uuid.UUID | None = None
    expected_config_version: uuid.UUID
    disclosure_accepted: bool


def view(session: Session, topic: Topic) -> ProjectTrainingPublic:
    link = session.get(ProjectTopic, topic.id)
    if not link:
        raise HTTPException(404, "项目学习路线不存在")
    source_run = session.get(ProjectRun, link.project_run_id)
    assert source_run and source_run.snapshot
    group = family(session, topic)
    active = active_route(session, topic)
    # Ponytail: replay the small account history in this read snapshot; no cache
    # or background projection. Family/list reads grow with retained versions/runs.
    value = _public(session, topic)
    for identity in family_topics(session, topic):
        if identity == topic.id:
            continue
        previous_topic = session.get(Topic, identity)
        assert previous_topic and previous_topic.user_id == topic.user_id
        history = _public(session, previous_topic)
        value.completed_node_ids = list(
            set(value.completed_node_ids + history.completed_node_ids)
        )
        value.runs.extend(history.runs)
    return ProjectTrainingPublic(
        topic=value,
        project_run_id=link.project_run_id,
        current=route(session, topic, topic.current_id),
        active=active[1] if active else None,
        active_topic_id=active[0] if active else None,
        family_id=group.root_topic_id if group else topic.id,
        source_repository=Snapshot.model_validate(source_run.snapshot).repository,
    )


def public(identity: uuid.UUID, user_id: uuid.UUID) -> ProjectTrainingPublic:
    with read_snapshot() as session:
        return view(session, owned(session, identity, user_id))


@router.get("")
def list_routes(user: VerifiedUser, response: Response) -> list[ProjectTrainingPublic]:
    response.headers["Cache-Control"] = "no-store"
    with read_snapshot() as session:
        return [
            view(session, item)
            for item in session.exec(
                select(Topic)
                .join(ProjectTopic)
                .where(Topic.user_id == user.id)
                .order_by(col(Topic.created_at).desc())
            ).all()
        ]


@router.get("/{topic_id}")
def read_route(
    topic_id: uuid.UUID, user: VerifiedUser, response: Response
) -> ProjectTrainingPublic:
    response.headers["Cache-Control"] = "no-store"
    return public(topic_id, user.id)


@router.post("/analyze", status_code=202)
def analyze_route(
    body: AnalyzeProject, user: VerifiedUser, session: SessionDep
) -> ProjectTrainingPublic:
    lock_owner(session, user.id)
    previous = session.get(TopicJob, body.request_id)
    if previous:
        source = session.get(ProjectInput, previous.id)
        if (
            previous.user_id != user.id
            or previous.topic_id != body.topic_id
            or previous.expected_version != body.expected_version
            or previous.config_version != body.expected_config_version
            or not source
            or source.project_run_id != body.project_run_id
            or source.previous_version_id != body.previous_version_id
        ):
            raise HTTPException(409, "请求身份已用于其他路线；请保留本机输入")
        return public(body.topic_id, user.id)
    source_run = session.exec(
        select(ProjectRun)
        .where(ProjectRun.id == body.project_run_id, ProjectRun.user_id == user.id)
        .with_for_update()
    ).one_or_none()
    if not source_run:
        raise HTTPException(404, "项目记录不存在")
    if not source_run.snapshot or not source_run.project_map:
        raise HTTPException(409, "尚无已读取的模块材料；请先完成项目地图读取")
    snapshot = Snapshot.model_validate(source_run.snapshot)
    mapped = ProjectMap.model_validate(source_run.project_map)
    if not any(f.kind == "module" for f in mapped.confirmed):
        raise HTTPException(
            409, "尚无已核实模块，当前语言或读取范围不足，不能据此生成案例"
        )
    config = session.get(ModelConfig, user.id, populate_existing=True)
    if not body.disclosure_accepted:
        raise HTTPException(
            422, "请确认已读取模块片段与目录发送至已保存模型，用于路线分析和核对"
        )
    if not config or config.revoked or config.version != body.expected_config_version:
        raise HTTPException(409, "配置已变化，请重新确认模型目的地")
    topic = session.get(Topic, body.topic_id)
    if topic and body.previous_version_id:
        raise HTTPException(409, "项目更新须创建新路线记录，不覆盖旧来源绑定")
    if topic:
        topic = owned(session, topic.id, user.id)
        link = session.get(ProjectTopic, topic.id)
        if not link or link.project_run_id != source_run.id:
            raise HTTPException(409, "路线不属于本次项目分析")
    else:
        topic = Topic(id=body.topic_id, user_id=user.id)
        session.add(topic)
        session.flush()
        session.add(ProjectTopic(topic_id=topic.id, project_run_id=source_run.id))
        if body.previous_version_id:
            link_update(
                session,
                topic,
                body.previous_version_id,
                snapshot.repository,
                body.expected_active_version,
            )
    compare(topic, body.expected_version)
    if session.exec(
        select(TopicJob.id).where(
            TopicJob.topic_id == topic.id,
            col(TopicJob.status).in_(["queued", "running", "stopping"]),
        )
    ).first():
        raise HTTPException(409, "已有路线分析，请等待或停止")
    job = TopicJob(
        id=body.request_id,
        user_id=user.id,
        topic_id=topic.id,
        expected_version=topic.current_id,
        input_text=f"{snapshot.repository.owner}/{snapshot.repository.name}@{snapshot.repository.commit}",
        config_version=config.version,
        destination=config.service_url,
        model_id=config.model_id,
        message="等待项目路线分析；尚未生成题目",
    )
    session.add(job)
    session.flush()
    session.add(
        ProjectInput(
            id=job.id,
            topic_id=topic.id,
            project_run_id=source_run.id,
            previous_version_id=body.previous_version_id,
            snapshot=snapshot.model_dump(mode="json"),
            project_map=mapped.model_dump(mode="json"),
        )
    )
    enqueue(session, job)
    session.commit()
    return public(topic.id, user.id)
