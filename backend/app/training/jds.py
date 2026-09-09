"""Authenticated JD routes with immutable provenance and explicit confirmation."""

import uuid

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict
from sqlmodel import Session, col, select

from app.api.deps import SessionDep
from app.capabilities.evidence_service import read_evidence
from app.model_config.models import ModelConfig
from app.model_config.service import lock_owner
from app.training.jd_models import JDAnalysis, JDDocument, JDTopic
from app.training.jd_rules import (
    Analysis,
    Document,
    EvidenceView,
    Route,
    evidence_for,
    propose,
)
from app.training.jd_service import is_jd, route, save
from app.training.projection import read_snapshot
from app.training.routes import VerifiedUser
from app.training.topic_models import Topic, TopicJob
from app.training.topic_service import compare, owned
from app.training.topics import AnalyzeRequest, TopicPublic, _public, enqueue

router = APIRouter(prefix="/jds", tags=["jds"])


class AnalysisPublic(BaseModel):
    document: Document
    analysis: Analysis | None
    evidence: list[list[EvidenceView]]


class JDPublic(BaseModel):
    topic: TopicPublic
    documents: list[AnalysisPublic]
    current: Route | None
    evidence: list[EvidenceView]
    node_evidence: dict[str, EvidenceView]
    semantic_reliability: str = "unverified"


class SelectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: uuid.UUID | None = None
    document_id: uuid.UUID
    role_index: int


def jd_owned(session: Session, identity: uuid.UUID, user_id: uuid.UUID) -> Topic:
    item = owned(session, identity, user_id)
    if not is_jd(session, identity):
        raise HTTPException(404, "JD 记录不存在")
    return item


def view(session: Session, item: Topic) -> JDPublic:
    current = route(session, item, item.current_id)
    evidence = read_evidence(session, item.user_id)
    return JDPublic(
        topic=_public(session, item),
        documents=[
            AnalysisPublic(
                document=Document(id=row.id, text=row.text),
                analysis=Analysis.model_validate(analysis.snapshot)
                if (analysis := session.get(JDAnalysis, row.id))
                else None,
                evidence=[
                    [
                        evidence_for(requirement, evidence)
                        for requirement in role.requirements
                    ]
                    for role in Analysis.model_validate(analysis.snapshot).roles
                ]
                if analysis
                else [],
            )
            for row in session.exec(
                select(JDDocument).where(JDDocument.topic_id == item.id)
            ).all()
        ],
        current=current,
        node_evidence={
            str(node.id): evidence_for(
                next(
                    mapping.requirement
                    for mapping in current.mappings
                    if mapping.node_id == node.id
                ).model_copy(update={"goal": node}),
                evidence,
            )
            for node in current.route.nodes
        }
        if current
        else {},
        evidence=[
            evidence_for(requirement, evidence) for requirement in current.requirements
        ]
        if current
        else [],
    )


def public(identity: uuid.UUID, user_id: uuid.UUID) -> JDPublic:
    with read_snapshot() as session:
        return view(session, jd_owned(session, identity, user_id))


@router.get("")
def list_jds(user: VerifiedUser, response: Response) -> list[JDPublic]:
    response.headers["Cache-Control"] = "no-store"
    with read_snapshot() as session:
        return [
            view(session, item)
            for item in session.exec(
                select(Topic)
                .join(JDTopic, col(JDTopic.topic_id) == col(Topic.id))
                .where(Topic.user_id == user.id)
                .order_by(col(Topic.created_at).desc())
            ).all()
        ]


@router.get("/{topic_id}")
def read_jd(topic_id: uuid.UUID, user: VerifiedUser, response: Response) -> JDPublic:
    response.headers["Cache-Control"] = "no-store"
    return public(topic_id, user.id)


@router.post("/analyze", status_code=202)
def analyze_jd(
    body: AnalyzeRequest, user: VerifiedUser, session: SessionDep
) -> JDPublic:
    if not body.input_text.strip() or body.expand:
        raise HTTPException(422, "请提供招聘原文；JD 不使用自由主题的分段扩展")
    lock_owner(session, user.id)
    previous = session.get(TopicJob, body.request_id)
    if previous:
        if (
            previous.user_id != user.id
            or previous.topic_id != body.topic_id
            or previous.input_text != body.input_text
            or previous.expected_version != body.expected_version
            or previous.config_version != body.expected_config_version
            or session.get(JDDocument, previous.id) is None
        ):
            raise HTTPException(409, "请求身份已用于另一份分析，请保留本机输入")
        return public(body.topic_id, user.id)
    if not body.disclosure_accepted:
        raise HTTPException(422, "请确认招聘原文与目录发送至已保存模型，用于分析与核对")
    config = session.get(ModelConfig, user.id, populate_existing=True)
    if not config or config.revoked or config.version != body.expected_config_version:
        raise HTTPException(409, "配置已变化或不可用，请重新确认目的地")
    item = session.get(Topic, body.topic_id)
    if item:
        jd_owned(session, item.id, user.id)
    else:
        item = Topic(id=body.topic_id, user_id=user.id)
        session.add(item)
        session.flush()
        session.add(JDTopic(topic_id=item.id))
    compare(item, body.expected_version)
    if session.exec(
        select(TopicJob.id).where(
            TopicJob.topic_id == item.id,
            col(TopicJob.status).in_(["queued", "running", "stopping"]),
        )
    ).first():
        raise HTTPException(409, "此 JD 已有分析，请等待或停止")
    job = TopicJob(
        id=body.request_id,
        user_id=user.id,
        topic_id=item.id,
        expected_version=item.current_id,
        input_text=body.input_text,
        config_version=config.version,
        destination=config.service_url,
        model_id=config.model_id,
        message="等待分析 JD；尚未选择岗位或生成题目",
    )
    session.add(job)
    session.flush()
    session.add(JDDocument(id=job.id, topic_id=item.id, text=body.input_text))
    enqueue(session, job)
    session.commit()
    return public(item.id, user.id)


@router.post("/{topic_id}/select")
def select_role(
    topic_id: uuid.UUID, body: SelectRequest, user: VerifiedUser, session: SessionDep
) -> JDPublic:
    item = owned(session, topic_id, user.id, lock=True)
    jd_owned(session, topic_id, user.id)
    compare(item, body.expected_version)
    document = session.get(JDDocument, body.document_id)
    analysis = session.get(JDAnalysis, body.document_id)
    if not document or document.topic_id != topic_id or not analysis:
        raise HTTPException(409, "请选择本 JD 已核对完成的分析")
    try:
        candidate = propose(
            Document(id=document.id, text=document.text),
            Analysis.model_validate(analysis.snapshot),
            selected_role=body.role_index,
            previous=route(session, item, item.current_id),
            expected_version=body.expected_version,
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    save(session, item, candidate)
    session.commit()
    return public(item.id, user.id)
