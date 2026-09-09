"""JD provenance adapters; Topic owns locks, attempts and confirmation pointers."""

import uuid

from fastapi import HTTPException
from sqlmodel import Session

from app.training.jd_models import JDAnalysis, JDDocument, JDRoute, JDTopic
from app.training.jd_rules import Analysis, Document, Mapping, Route, propose
from app.training.topic_analysis import Inspection
from app.training.topic_models import Topic, TopicJob
from app.training.topic_rules import Version
from app.training.topic_service import save_version


def is_jd(session: Session, topic_id: uuid.UUID) -> bool:
    return session.get(JDTopic, topic_id) is not None


def route(session: Session, topic: Topic, identity: uuid.UUID | None) -> Route | None:
    if identity is None:
        return None
    row = session.get(JDRoute, identity)
    if row is None:
        raise HTTPException(409, "JD 来源关联不可用，旧记录保留")
    document = session.get(JDDocument, row.document_id)
    if not document or document.topic_id != topic.id:
        raise HTTPException(404, "路线不属于此 JD")
    return Route.model_validate(row.snapshot)


def save(session: Session, topic: Topic, candidate: Route) -> None:
    save_version(session, topic, candidate.route)
    session.flush()
    session.add(
        JDRoute(
            version_id=candidate.route.id,
            document_id=candidate.document.id,
            snapshot=candidate.model_dump(mode="json"),
        )
    )


def validate(document: Document, candidate: Analysis) -> None:
    # Run exact quote/catalog validation across every role without choosing one.
    for index in range(len(candidate.roles)):
        propose(document, candidate, selected_role=index)


def save_edit(session: Session, topic: Topic, candidate: Version) -> None:
    old = route(session, topic, topic.current_id)
    assert old is not None
    by_id = {mapping.node_id: mapping for mapping in old.mappings}
    mappings = []
    for index, node in enumerate(candidate.nodes):
        previous = by_id.get(node.id)
        if previous is None:
            previous = by_id[old.route.nodes[index].id]
        # Keep the employer claim immutable. The edited training card is stored
        # separately in Version; user preference is never rewritten as JD fact.
        mappings.append(Mapping(node_id=node.id, requirement=previous.requirement))
    save(
        session,
        topic,
        old.model_copy(update={"route": candidate, "mappings": tuple(mappings)}),
    )


def generation_goal(selection: dict[str, object]) -> dict[str, str]:
    goal = {"goal": str(selection["goal"]), "focus": str(selection["focus"])}
    if selection.get("entry") == "jd":
        for field in ("requirement_quote", "basis", "simulation_label"):
            goal[field] = str(selection[field])
    return goal


def accept(session: Session, topic: Topic, item: TopicJob, raw: str) -> None:
    stored = session.get(JDDocument, item.id)
    assert stored is not None and stored.topic_id == topic.id
    document = Document(id=stored.id, text=stored.text)
    if item.stage == "analyze":
        candidate = Analysis.model_validate_json(raw)
        validate(document, candidate)
        item.candidate = candidate.model_dump(mode="json")
        item.stage = "inspect"
        return
    inspection = Inspection.model_validate_json(raw)
    if not inspection.accepted or not inspection.explanation.strip():
        raise ValueError("JD analysis failed content inspection")
    candidate = Analysis.model_validate(item.candidate)
    validate(document, candidate)
    session.add(
        JDAnalysis(document_id=document.id, snapshot=candidate.model_dump(mode="json"))
    )
    item.result_id = document.id
    item.status, item.code, item.message = (
        "completed",
        "ok",
        "JD 分析已核对，请选择岗位、调整并确认路线；尚未生成题目",
    )
