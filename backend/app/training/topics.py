import uuid
from typing import Literal

import procrastinate
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict
from sqlmodel import Session, col, select

from app.api.deps import SessionDep
from app.capabilities.catalog import CATALOG
from app.capabilities.unlocks import open_unit
from app.model_config.models import ModelConfig
from app.model_config.service import lock_owner
from app.training.independent_routes import enqueue as enqueue_training
from app.training.jd_models import JDTopic
from app.training.models import TrainingRun
from app.training.projection import read_snapshot
from app.training.queue import DSN
from app.training.routes import TaskPublic, VerifiedUser
from app.training.routes import view as training_view
from app.training.topic_models import Topic, TopicJob, TopicVersion
from app.training.topic_rules import Goal, Node, Version, confirm, input_action
from app.training.topic_service import compare, owned, save_version, version
from app.training.topic_worker import analyze_topic, stage_exhausted

router = APIRouter(prefix="/topics", tags=["topics"])


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID
    topic_id: uuid.UUID
    expected_version: uuid.UUID | None = None
    input_text: str
    expand: bool = False
    expected_config_version: uuid.UUID
    disclosure_accepted: bool


class EditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: uuid.UUID
    operation: Literal["edit", "reorder"]
    node_id: uuid.UUID | None = None
    goal: Goal | None = None
    order: list[uuid.UUID] | None = None


class VersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: uuid.UUID


class StartRequest(VersionRequest):
    request_id: uuid.UUID
    node_id: uuid.UUID
    expected_config_version: uuid.UUID
    disclosure_accepted: bool


class JobPublic(BaseModel):
    id: uuid.UUID
    topic_id: uuid.UUID
    status: str
    message: str
    input_text: str
    result_id: uuid.UUID | None
    attempts: int
    destination: str
    model_id: str


class TopicPublic(BaseModel):
    id: uuid.UUID
    current: Version | None
    active_id: uuid.UUID | None
    versions: list[Version]
    jobs: list[JobPublic]
    runs: list[TaskPublic]
    completed_node_ids: list[uuid.UUID]


def public(_session: Session, item: Topic) -> TopicPublic:
    # All mutation callers commit before projecting; terminal/duplicate paths
    # have no pending writes. Do not release their locks or wait for model gates.
    with read_snapshot() as snapshot:
        current = snapshot.get(Topic, item.id)
        assert current is not None
        return _public(snapshot, current)


def _public(session: Session, item: Topic) -> TopicPublic:
    # ponytail: reads this route's retained versions/runs in full; intended for small
    # personal histories. Measure large histories before adding pagination, not a
    # learning expiry or an artificial limit on accumulated progress.
    versions = session.exec(
        select(TopicVersion).where(TopicVersion.topic_id == item.id)
    ).all()
    jobs = session.exec(select(TopicJob).where(TopicJob.topic_id == item.id)).all()
    runs = session.exec(
        select(TrainingRun).where(
            TrainingRun.user_id == item.user_id,
            col(TrainingRun.selection)["topic_id"].as_string() == str(item.id),
        )
    ).all()
    return TopicPublic(
        id=item.id,
        current=version(session, item, item.current_id),
        active_id=item.active_id,
        versions=[Version.model_validate(row.snapshot) for row in versions],
        jobs=[JobPublic.model_validate(row, from_attributes=True) for row in jobs],
        completed_node_ids=list(
            {
                uuid.UUID(row.selection["topic_node_id"])
                for row in runs
                if row.formal_submitted_at and row.selection.get("topic_node_id")
            }
        ),
        runs=[
            training_view(session, row)
            for row in runs
            if row.selection.get("topic_id") == str(item.id)
        ],
    )


def enqueue(session: Session, job: TopicJob) -> None:
    app = procrastinate.App(connector=procrastinate.SyncPsycopgConnector(conninfo=DSN))
    task = app.task(name="topic.analyze")(analyze_topic.func)
    job.queue_job_id = task.configure(
        connection=session.connection().connection.driver_connection, lock=str(job.id)
    ).defer(topic_job_id=str(job.id))
    session.add(job)


@router.get("")
def list_topics(
    user: VerifiedUser, _session: SessionDep, response: Response
) -> list[TopicPublic]:
    response.headers["Cache-Control"] = "no-store"
    with read_snapshot() as snapshot:
        return [
            _public(snapshot, item)
            for item in snapshot.exec(
                select(Topic)
                .where(
                    Topic.user_id == user.id,
                    col(Topic.id).not_in(select(JDTopic.topic_id)),
                )
                .order_by(col(Topic.created_at).desc())
            ).all()
        ]


@router.get("/{topic_id}")
def read_topic(
    topic_id: uuid.UUID, user: VerifiedUser, session: SessionDep, response: Response
) -> TopicPublic:
    response.headers["Cache-Control"] = "no-store"
    return public(session, owned(session, topic_id, user.id))


@router.post("/analyze", status_code=202)
def request_analysis(
    body: AnalyzeRequest, user: VerifiedUser, session: SessionDep
) -> TopicPublic:
    if input_action(body.input_text) == "random":
        raise HTTPException(422, "主题为空，请使用随机练习入口")
    lock_owner(session, user.id)
    existing = session.get(TopicJob, body.request_id)
    if existing:
        if (
            existing.user_id != user.id
            or any(
                getattr(existing, field) != getattr(body, field)
                for field in ("topic_id", "input_text", "expected_version", "expand")
            )
            or existing.config_version != body.expected_config_version
        ):
            raise HTTPException(409, "请求身份已用于其他主题分析")
        return public(session, owned(session, body.topic_id, user.id))
    config = session.get(ModelConfig, user.id, populate_existing=True)
    if not body.disclosure_accepted:
        raise HTTPException(
            422, "请确认主题文本、旧路线及目录会发送给已保存模型，重试可能计费"
        )
    if not config or config.revoked or config.version != body.expected_config_version:
        raise HTTPException(409, "配置不可用或已变化，请重新确认接收方")
    item = session.get(Topic, body.topic_id)
    if item:
        item = owned(session, item.id, user.id, lock=True)
        from app.training.jd_service import is_jd

        if is_jd(session, item.id):
            raise HTTPException(409, "请从 JD 入口更新招聘原文")
    else:
        item = Topic(id=body.topic_id, user_id=user.id)
        session.add(item)
        session.flush()
    compare(item, body.expected_version)
    if body.expand and (
        not (current := version(session, item, item.current_id))
        or current.kind != "broad"
    ):
        raise HTTPException(422, "只有已有宽泛路线可以逐段展开")
    if session.exec(
        select(TopicJob.id).where(
            TopicJob.topic_id == item.id,
            col(TopicJob.status).in_(["queued", "running", "stopping"]),
        )
    ).first():
        raise HTTPException(409, "此主题已有分析，请等待或停止")
    job = TopicJob(
        id=body.request_id,
        user_id=user.id,
        topic_id=item.id,
        expected_version=item.current_id,
        input_text=body.input_text,
        expand=body.expand,
        config_version=config.version,
        destination=config.service_url,
        model_id=config.model_id,
    )
    session.add(job)
    session.flush()
    enqueue(session, job)
    session.commit()
    return public(session, item)


@router.post("/{topic_id}/edit")
def edit_topic(
    topic_id: uuid.UUID, body: EditRequest, user: VerifiedUser, session: SessionDep
) -> TopicPublic:
    item = owned(session, topic_id, user.id, lock=True)
    compare(item, body.expected_version)
    old = version(session, item, item.current_id)
    assert old
    if old.catalog_version != CATALOG.version:
        raise HTTPException(409, "目录已变化，请重新分析")
    if not old.nodes or old.kind not in {"clear", "broad"}:
        raise HTTPException(409, "此版本尚无可编辑目标，请重写或澄清")
    nodes = list(old.nodes)
    if body.operation == "reorder":
        if (
            body.order is None
            or len(body.order) != len(nodes)
            or set(body.order) != {n.id for n in nodes}
        ):
            raise HTTPException(422, "重排必须包含所有现有节点且各一次")
        by_id = {n.id: n for n in nodes}
        nodes = [by_id[identity] for identity in body.order]
    else:
        if body.goal is None or body.node_id not in {n.id for n in nodes}:
            raise HTTPException(422, "请指定现有节点和完整目标卡")
        from app.capabilities.unlocks import level_for

        level_for(body.goal.target)
        nodes = [
            Node(id=uuid.uuid4(), **body.goal.model_dump())
            if n.id == body.node_id
            and n.model_dump(exclude={"id"}) != body.goal.model_dump()
            else n
            for n in nodes
        ]
    recommended = old.recommended_id
    if recommended not in {n.id for n in nodes}:
        recommended = nodes[
            next(i for i, n in enumerate(old.nodes) if n.id == old.recommended_id)
        ].id
    candidate = old.model_copy(
        update={
            "id": uuid.uuid4(),
            "parent_id": old.id,
            "nodes": tuple(nodes),
            "recommended_id": recommended,
            "confirmed": False,
        }
    )
    from app.training.jd_service import is_jd, save_edit

    if is_jd(session, item.id):
        save_edit(session, item, candidate)
    else:
        save_version(session, item, candidate)
    session.commit()
    return public(session, item)


@router.post("/{topic_id}/confirm")
def confirm_topic(
    topic_id: uuid.UUID, body: VersionRequest, user: VerifiedUser, session: SessionDep
) -> TopicPublic:
    item = owned(session, topic_id, user.id, lock=True)
    compare(item, body.expected_version)
    current = version(session, item, item.current_id)
    assert current
    try:
        confirm(current, body.expected_version)
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
    item.active_id = current.id
    session.add(item)
    session.commit()
    return public(session, item)


@router.post("/{topic_id}/start", status_code=202)
def start_topic(
    topic_id: uuid.UUID, body: StartRequest, user: VerifiedUser, session: SessionDep
) -> TaskPublic:
    item = owned(session, topic_id, user.id, lock=True)
    existing = session.get(TrainingRun, body.request_id)
    if existing:
        if (
            existing.user_id != user.id
            or existing.selection.get("topic_id") != str(topic_id)
            or existing.selection.get("topic_version_id") != str(body.expected_version)
            or existing.selection.get("topic_node_id") != str(body.node_id)
            or existing.config_version != body.expected_config_version
        ):
            raise HTTPException(409, "请求身份已用于其他题目")
        return training_view(session, existing)
    compare(item, body.expected_version)
    if item.active_id != body.expected_version:
        raise HTTPException(409, "请先显式确认当前版本")
    current = version(session, item, item.active_id)
    assert current
    node = next((n for n in current.nodes if n.id == body.node_id), None)
    if not node or current.catalog_version != CATALOG.version:
        raise HTTPException(409, "节点或目录已变化，请重新确认")
    config = session.get(ModelConfig, user.id, populate_existing=True)
    if not body.disclosure_accepted:
        raise HTTPException(422, "请确认目标、重点、必要来源和模型接收方")
    if not config or config.revoked or config.version != body.expected_config_version:
        raise HTTPException(409, "配置已变化，请重新确认接收方")
    if session.exec(
        select(TrainingRun.id).where(
            TrainingRun.user_id == user.id,
            col(TrainingRun.status).in_(["queued", "running", "stopping"]),
        )
    ).first():
        raise HTTPException(409, "已有生成任务，请等待或停止")
    open_unit(session, user.id, node.target)
    run = TrainingRun(
        id=body.request_id,
        user_id=user.id,
        config_version=config.version,
        destination=config.service_url,
        model_id=config.model_id,
        target=node.target.model_dump(),
        selection={
            "catalog_version": CATALOG.version,
            "entry": "free_topic",
            "goal": node.text,
            "focus": node.focus,
            "topic_id": str(item.id),
            "topic_version_id": str(current.id),
            "topic_node_id": str(node.id),
        },
    )
    from app.training.jd_service import is_jd
    from app.training.jd_service import route as jd_route

    if is_jd(session, item.id):
        frozen = jd_route(session, item, current.id)
        assert frozen is not None
        mapping = next(m for m in frozen.mappings if m.node_id == node.id)
        run.selection = {
            **run.selection,
            "entry": "jd",
            "jd_document_id": str(frozen.document.id),
            "jd_role_name": frozen.role_name,
            "requirement_quote": mapping.requirement.quote.text,
            "basis": mapping.requirement.basis,
            "simulation_label": "教学模拟",
        }
    session.add(run)
    session.flush()
    enqueue_training(session, run)
    session.commit()
    return training_view(session, run)


@router.post("/{topic_id}/jobs/{job_id}/{action}")
def job_action(
    topic_id: uuid.UUID,
    job_id: uuid.UUID,
    action: Literal["stop", "retry"],
    user: VerifiedUser,
    session: SessionDep,
) -> TopicPublic:
    owned(session, topic_id, user.id)
    job = session.exec(
        select(TopicJob)
        .where(TopicJob.id == job_id, TopicJob.topic_id == topic_id)
        .with_for_update()
    ).one_or_none()
    if not job:
        raise HTTPException(404, "分析任务不存在")
    if action == "stop":
        if job.status not in {"completed", "failed", "stopped"}:
            job.stop_requested = True
            job.status, job.code, job.message = (
                "stopping",
                "stopping",
                "正在停止分析，请等待确认；旧路线保留",
            )
            job_identity = job.queue_job_id
            session.add(job)
            session.commit()
            with procrastinate.App(
                connector=procrastinate.SyncPsycopgConnector(conninfo=DSN)
            ).open() as app:
                if job_identity is not None:
                    app.job_manager.cancel_job_by_id(job_identity, abort=True)
            lock_owner(session, user.id)
            job = session.exec(
                select(TopicJob)
                .where(TopicJob.id == job_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).one()
            if (
                job.queue_job_id == job_identity
                and job.stop_requested
                and job.status == "stopping"
            ):
                job.status, job.code, job.message = (
                    "stopped",
                    "stopped",
                    "已停止分析，旧路线保留；在途调用仍可能计费",
                )
                session.add(job)
                session.commit()
    else:
        session.rollback()
        item = owned(session, topic_id, user.id, lock=True)
        job = session.get(TopicJob, job_id, populate_existing=True)
        assert job
        compare(item, job.expected_version)
        config = session.get(ModelConfig, user.id, populate_existing=True)
        if not config or config.revoked or config.version != job.config_version:
            raise HTTPException(409, "配置变化，请明确确认后新建分析")
        if (
            job.status not in {"failed", "stopped"}
            or job.attempts >= 6
            or stage_exhausted(session, job)
        ):
            raise HTTPException(409, "任务不可重试或预算已耗尽")
        job.attempt_limit = min(6, job.attempts + 3)
        job.stop_requested = False
        job.status, job.code, job.message = (
            "queued",
            "queued",
            "主动恢复分析，沿用已存预算与输入",
        )
        enqueue(session, job)
        session.commit()
    return public(session, owned(session, topic_id, user.id))
