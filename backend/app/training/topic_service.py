import uuid

from fastapi import HTTPException
from sqlmodel import Session, select

from app.model_config.service import lock_owner
from app.training.topic_models import Topic, TopicVersion
from app.training.topic_rules import Version


def owned(
    session: Session, identity: uuid.UUID, user_id: uuid.UUID, *, lock: bool = False
) -> Topic:
    if lock:
        lock_owner(session, user_id)
    query = select(Topic).where(Topic.id == identity, Topic.user_id == user_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    item = session.exec(query).one_or_none()
    if not item:
        raise HTTPException(404, "主题记录不存在")
    return item


def version(
    session: Session, topic: Topic, identity: uuid.UUID | None
) -> Version | None:
    if identity is None:
        return None
    row = session.get(TopicVersion, identity)
    if not row or row.topic_id != topic.id:
        raise HTTPException(404, "路线版本不属于此主题")
    return Version.model_validate(row.snapshot)


def compare(topic: Topic, expected: uuid.UUID | None) -> None:
    if topic.current_id != expected:
        raise HTTPException(409, "路线已变化；保留本机编辑，请读取并比较后重新操作")


def save_version(session: Session, topic: Topic, candidate: Version) -> None:
    session.add(
        TopicVersion(
            id=candidate.id,
            topic_id=topic.id,
            snapshot=candidate.model_dump(mode="json"),
        )
    )
    topic.current_id = candidate.id
    session.add(topic)
