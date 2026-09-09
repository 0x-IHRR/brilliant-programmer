"""Owned concept requests, explicit publication and content-bound rendering receipts."""

import hashlib
import json
import secrets
import uuid
from datetime import UTC, datetime
from typing import Literal, cast

import procrastinate
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, col, select

from app.api.deps import SessionDep
from app.model_config.connection import Attempt
from app.model_config.models import ModelConfig
from app.model_config.output import check_output
from app.model_config.service import decrypt, lock_owner
from app.training.concept import context_for, help_content, safe_guidance
from app.training.concept_delivery import observe_delivery
from app.training.concept_models import ConceptAttempt, ConceptHelp, HelpDelivery
from app.training.concept_schema import (
    ConceptContent,
    ContentReview,
    Direction,
    HelpInput,
    classify_content,
)
from app.training.concept_worker import finish_stop, generate_help
from app.training.evaluation_models import Evaluation
from app.training.events import next_event
from app.training.guided import GuidanceDraft, guidance_draft
from app.training.independent import Confirmation, Digest, publication_permission
from app.training.independent_models import HelpConfirmation
from app.training.independent_service import record_frozen
from app.training.models import TrainingRun
from app.training.queue import DSN
from app.training.routes import VerifiedUser, owned
from app.training.schema import Candidate, Source
from app.training.submission_worker import RETRYABLE

router = APIRouter(prefix="/training", tags=["concepts"])


class HelpCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID
    kind: Literal["concept", "hint", "demonstration"] = "concept"
    expected_config_version: uuid.UUID
    disclosure_accepted: bool
    input: HelpInput
    parent_id: uuid.UUID | None = None


class PublicDelivery(BaseModel):
    id: uuid.UUID
    sequence: int
    exposure_sequence: int
    attempt_id: uuid.UUID | None
    status: str
    delivered_text: str
    direction: str | None
    occurred_at: datetime
    evidence: str


class HelpPublic(BaseModel):
    kind: str
    id: uuid.UUID
    run_id: uuid.UUID
    parent_id: uuid.UUID | None
    input: HelpInput
    created_sequence: int
    generated_sequence: int | None
    checked_sequence: int | None
    status: str
    code: str
    message: str
    destination: str
    model_id: str
    direction: str | None
    requires_independent_confirmation: bool
    confirmation_prompt: str | None
    content_hash: str | None
    attempts: list[Attempt]
    deliveries: list[PublicDelivery]
    can_retry: bool


class HelpPublication(BaseModel):
    help_id: uuid.UUID
    delivery_id: uuid.UUID
    receipt_token: str
    content: ConceptContent | GuidanceDraft
    content_hash: str
    sections: dict[str, str]
    exposure_sequence: int


class RenderingReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=32, max_length=200)


def enqueue(session: Session, item: ConceptHelp) -> None:
    app = procrastinate.App(connector=procrastinate.SyncPsycopgConnector(conninfo=DSN))
    task = app.task(name="training.concept")(generate_help.func)
    item.queue_job_id = task.configure(
        connection=session.connection().connection.driver_connection,
        lock="concept:" + str(item.id),
    ).defer(help_id=str(item.id))
    session.add(item)


def help_owned(
    session: Session, run_id: uuid.UUID, help_id: uuid.UUID, user_id: uuid.UUID
) -> ConceptHelp:
    owned(session, run_id, user_id)
    item = session.get(ConceptHelp, help_id, populate_existing=True)
    if not item or item.run_id != run_id:
        raise HTTPException(404, "帮助不存在")
    return item


def view(session: Session, item: ConceptHelp) -> HelpPublic:
    session.refresh(item)
    run = session.get(TrainingRun, item.run_id, populate_existing=True)
    assert run
    permission = publication_permission(
        run_id=run.id,
        help_id=item.id,
        content_hash="",
        sequence=run.event_sequence + 1,
        mode="independent"
        if run.launch_mode == "independent" and run.converted_sequence is None
        else "practice",
        direction=cast(Direction, item.direction)
        if item.direction in {"neutral", "directional", "uncertain"}
        else "uncertain",
    )
    digest = None
    if item.status == "ready" and item.content:
        digest = hashlib.sha256(
            "\n\n".join(
                help_content(item.kind, item.content).sections().values()
            ).encode()
        ).hexdigest()
    return HelpPublic(
        **item.model_dump(
            include={
                "id",
                "kind",
                "run_id",
                "parent_id",
                "status",
                "code",
                "message",
                "destination",
                "model_id",
                "direction",
                "created_sequence",
                "generated_sequence",
                "checked_sequence",
            }
        ),
        input=HelpInput.model_validate(item.request),
        requires_independent_confirmation=not permission.allowed,
        confirmation_prompt=permission.prompt,
        content_hash=digest,
        attempts=[
            Attempt(
                **a.model_dump(
                    include={
                        "number",
                        "code",
                        "prompt_tokens",
                        "completion_tokens",
                        "total_tokens",
                    }
                )
            )
            for a in session.exec(
                select(ConceptAttempt)
                .where(ConceptAttempt.help_id == item.id)
                .order_by(col(ConceptAttempt.number))
            ).all()
        ],
        deliveries=[
            PublicDelivery(**d.model_dump())
            for d in session.exec(
                select(HelpDelivery)
                .where(HelpDelivery.help_id == item.id)
                .order_by(col(HelpDelivery.sequence))
            ).all()
        ],
        can_retry=item.status in {"failed", "stopped"}
        and item.attempts < 6
        and item.code
        in RETRYABLE | {"internal_failure", "budget_exhausted", "stopped"},
    )


@router.get("/tasks/{run_id}/help")
def list_help(
    run_id: uuid.UUID, session: SessionDep, user: VerifiedUser, response: Response
) -> list[HelpPublic]:
    response.headers["Cache-Control"] = "no-store"
    owned(session, run_id, user.id)
    return [
        view(session, item)
        for item in session.exec(
            select(ConceptHelp)
            .where(ConceptHelp.run_id == run_id)
            .order_by(col(ConceptHelp.created_sequence))
        ).all()
    ]


@router.post("/tasks/{run_id}/help", status_code=202)
def request_help(
    run_id: uuid.UUID,
    body: HelpCreate,
    session: SessionDep,
    user: VerifiedUser,
    response: Response,
) -> HelpPublic:
    response.headers["Cache-Control"] = "no-store"
    run = owned(session, run_id, user.id)
    lock_owner(session, user.id)
    session.refresh(run)
    existing = session.get(ConceptHelp, body.request_id)
    if existing:
        if (
            existing.run_id != run_id
            or existing.kind != body.kind
            or existing.request != body.input.model_dump()
            or existing.parent_id != body.parent_id
            or existing.config_version != body.expected_config_version
        ):
            raise HTTPException(409, "请求标识已用于其他帮助，输入保留；请重读现有状态")
        return view(session, existing)
    if run.status != "completed" or not run.candidate:
        raise HTTPException(409, "请先取得当前完整案例；无需先作答")
    active = session.exec(
        select(ConceptHelp.id).where(
            ConceptHelp.run_id == run_id,
            col(ConceptHelp.status).in_(["checking", "stopping"]),
        )
    ).first()
    if active:
        raise HTTPException(409, "本轮已有帮助正在处理，请读取现有状态或停止")
    if not body.disclosure_accepted:
        raise HTTPException(
            422, "请确认将当前案例、作答、求助和必要帮助记录发给已保存模型；可能计费"
        )
    config = session.get(ModelConfig, user.id, populate_existing=True)
    if not config or config.revoked or config.version != body.expected_config_version:
        raise HTTPException(409, "配置已变化，请重新读取并确认模型目的地")
    if body.kind != "concept" and (body.parent_id or body.input.depth != "basic"):
        raise HTTPException(422, "提示和示范不附带概念深入历史")
    history = []
    if body.input.depth == "deep":
        parent = (
            help_owned(session, run_id, body.parent_id, user.id)
            if body.parent_id
            else None
        )
        seen = session.exec(
            select(HelpDelivery.id).where(
                HelpDelivery.help_id == body.parent_id,
                HelpDelivery.status == "delivered",
            )
        ).first()
        if not parent or parent.kind != "concept" or not parent.content or not seen:
            raise HTTPException(409, "请先查看并确认当前概念说明，再主动展开原理")
        history.append(ConceptContent.model_validate(parent.content))
    elif body.parent_id:
        raise HTTPException(422, "基础说明不附带其他帮助历史")
    try:
        context = context_for(
            Candidate.model_validate(run.candidate),
            [Source.model_validate(s) for s in run.sources],
            body.input,
            history,
        )
        check_output(
            json.dumps(context, ensure_ascii=False), decrypt(config).get_secret_value()
        )
    except ValueError:
        raise HTTPException(
            422, "请检查当前判断与求助内容；疑似秘密不发送，请脱敏"
        ) from None
    draft = None
    if body.kind != "concept":
        try:
            draft = guidance_draft(
                Candidate.model_validate(run.candidate),
                [Source.model_validate(s) for s in run.sources],
                body.kind,
                decrypt(config).get_secret_value(),
            )
            safe_guidance(draft, decrypt(config).get_secret_value())
        except ValueError:
            raise HTTPException(
                422, "冻结材料暂不适合安全示范；未交付，请保留原题记录"
            ) from None
    item = ConceptHelp(
        kind=body.kind,
        id=body.request_id,
        created_sequence=next_event(session, run_id),
        run_id=run_id,
        parent_id=body.parent_id,
        request=body.input.model_dump(),
        config_version=config.version,
        destination=config.service_url,
        model_id=config.model_id,
    )
    if draft:
        item.content = draft.model_dump(mode="json")
        item.generated_sequence = next_event(session, run_id)
        item.stage = "inspect"
    session.add(item)
    session.flush()
    enqueue(session, item)
    session.commit()
    return view(session, item)


@router.post("/tasks/{run_id}/help/{help_id}/retry", status_code=202)
def retry_help(
    run_id: uuid.UUID,
    help_id: uuid.UUID,
    session: SessionDep,
    user: VerifiedUser,
    response: Response,
) -> HelpPublic:
    response.headers["Cache-Control"] = "no-store"
    item = help_owned(session, run_id, help_id, user.id)
    lock_owner(session, user.id)
    session.refresh(item)
    if item.status in {"checking", "ready"}:
        return view(session, item)
    if not view(session, item).can_retry:
        raise HTTPException(409, "当前帮助不可重试或预算耗尽；输入与记录保留")
    config = session.get(ModelConfig, user.id, populate_existing=True)
    if not config or config.revoked or config.version != item.config_version:
        raise HTTPException(409, "旧配置已撤销；请核对新目的地后主动发起新的帮助")
    item.status, item.code, item.message = (
        "checking",
        "queued",
        "继续本次帮助，阶段与预算保留",
    )
    item.stop_requested = False
    item.attempt_limit = min(6, item.stage_attempts + 3)
    enqueue(session, item)
    session.commit()
    return view(session, item)


@router.post("/tasks/{run_id}/help/{help_id}/stop")
def stop_help(
    run_id: uuid.UUID,
    help_id: uuid.UUID,
    session: SessionDep,
    user: VerifiedUser,
    response: Response,
) -> HelpPublic:
    response.headers["Cache-Control"] = "no-store"
    item = help_owned(session, run_id, help_id, user.id)
    item = session.exec(
        select(ConceptHelp)
        .where(ConceptHelp.id == item.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    if item.status not in {"checking", "stopping"}:
        return view(session, item)
    job_id = item.queue_job_id
    item.stop_requested, item.status = True, "stopping"
    session.add(item)
    session.commit()
    finish_stop(item.id, job_id)
    return view(session, item)


class ConfirmHelp(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content_hash: Digest
    accepted: bool


class PublicationChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation_id: uuid.UUID | None = None


class ConfirmationReceipt(BaseModel):
    id: uuid.UUID


@router.post("/tasks/{run_id}/help/{help_id}/confirm")
def confirm_help(
    run_id: uuid.UUID,
    help_id: uuid.UUID,
    body: ConfirmHelp,
    session: SessionDep,
    user: VerifiedUser,
    response: Response,
) -> ConfirmationReceipt:
    response.headers["Cache-Control"] = "no-store"
    item = help_owned(session, run_id, help_id, user.id)
    lock_owner(session, user.id)
    session.refresh(item)
    if (
        item.status != "ready"
        or not item.content
        or not item.inspection
        or not body.accepted
    ):
        raise HTTPException(409, "尚未确认本次可交付说明")
    content = help_content(item.kind, item.content)
    direction = classify_content(content, ContentReview.model_validate(item.inspection))
    digest = hashlib.sha256(
        "\n\n".join(content.sections().values()).encode()
    ).hexdigest()
    if digest != body.content_hash:
        raise HTTPException(409, "内容版本变化，请重新确认")
    event = HelpConfirmation(
        run_id=run_id,
        help_id=help_id,
        content_hash=digest,
        direction=direction,
        sequence=next_event(session, run_id),
    )
    session.add(event)
    session.commit()
    return ConfirmationReceipt(id=event.id)


@router.post("/tasks/{run_id}/help/{help_id}/deliver")
def publish_help(
    run_id: uuid.UUID,
    help_id: uuid.UUID,
    session: SessionDep,
    user: VerifiedUser,
    response: Response,
    body: PublicationChoice | None = None,
) -> HelpPublication:
    response.headers["Cache-Control"] = "no-store"
    item = help_owned(session, run_id, help_id, user.id)
    lock_owner(session, user.id)
    session.refresh(item)
    if item.status != "ready" or not item.content or not item.inspection:
        raise HTTPException(409, "说明尚不可交付；请读取帮助状态")
    content = help_content(item.kind, item.content)
    direction = classify_content(content, ContentReview.model_validate(item.inspection))
    text = "\n\n".join(content.sections().values())
    digest = hashlib.sha256(text.encode()).hexdigest()
    run = session.get(TrainingRun, run_id, populate_existing=True)
    assert run
    consent = (
        session.get(HelpConfirmation, body.confirmation_id)
        if body and body.confirmation_id
        else None
    )
    permission = publication_permission(
        run_id=run_id,
        help_id=help_id,
        content_hash=digest,
        sequence=run.event_sequence + 1,
        mode="independent"
        if run.launch_mode == "independent" and run.converted_sequence is None
        else "practice",
        direction=direction,
        confirmation=Confirmation.model_validate(consent.model_dump(exclude={"id"}))
        if consent
        else None,
    )
    if not permission.allowed:
        raise HTTPException(409, permission.prompt)
    token = secrets.token_urlsafe(32)
    sequence = next_event(session, run_id)
    event = HelpDelivery(
        help_id=help_id,
        run_id=run_id,
        sequence=sequence,
        exposure_sequence=sequence,
        status="delivery_unknown",
        content_hash=digest,
        receipt_hash=hashlib.sha256(token.encode()).hexdigest(),
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return HelpPublication(
        help_id=help_id,
        delivery_id=event.id,
        receipt_token=token,
        content=content,
        sections=content.sections(),
        content_hash=event.content_hash,
        exposure_sequence=sequence,
    )


@router.post("/tasks/{run_id}/help/{help_id}/deliveries/{delivery_id}/receipt")
def confirm_rendering(
    run_id: uuid.UUID,
    help_id: uuid.UUID,
    delivery_id: uuid.UUID,
    body: RenderingReceipt,
    session: SessionDep,
    user: VerifiedUser,
    response: Response,
) -> HelpPublic:
    response.headers["Cache-Control"] = "no-store"
    item = help_owned(session, run_id, help_id, user.id)
    lock_owner(session, user.id)
    attempt = session.get(HelpDelivery, delivery_id)
    if (
        not attempt
        or attempt.help_id != help_id
        or attempt.run_id != run_id
        or not attempt.receipt_hash
        or not secrets.compare_digest(
            attempt.receipt_hash, hashlib.sha256(body.token.encode()).hexdigest()
        )
    ):
        raise HTTPException(400, "交付回执无效；不能据此确认内容")
    existing = session.exec(
        select(HelpDelivery.id).where(HelpDelivery.attempt_id == delivery_id)
    ).first()
    if existing:
        return view(session, item)
    content = help_content(item.kind, item.content)
    review = ContentReview.model_validate(item.inspection)
    text = "\n\n".join(content.sections().values())
    if hashlib.sha256(text.encode()).hexdigest() != attempt.content_hash:
        raise HTTPException(409, "内容版本与交付尝试不一致")
    fact = observe_delivery(
        help_id=help_id,
        sequence=next_event(session, run_id),
        occurred_at=datetime.now(UTC),
        content=content,
        review=review,
        status="delivered",
        observed_text=text,
    )
    event = HelpDelivery(
        **fact.model_dump(exclude={"classification_version"}),
        run_id=run_id,
        exposure_sequence=attempt.sequence,
        attempt_id=attempt.id,
        content_hash=attempt.content_hash,
        evidence="content_bound_browser_render_receipt",
    )
    session.add(event)
    if fact.direction in {"directional", "uncertain"}:
        run = session.get(TrainingRun, run_id, populate_existing=True)
        assert run
        if run.launch_mode == "independent" and run.converted_sequence is None:
            run.converted_sequence = attempt.exposure_sequence
            session.add(run)
    session.flush()
    evaluation = session.get(Evaluation, run_id)
    run = session.get(TrainingRun, run_id)
    if evaluation and run:
        record_frozen(session, run, evaluation)
    session.commit()
    return view(session, item)
