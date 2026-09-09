"""Owner-scoped first Boss admission; points permit starting, never promotion."""

import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, field_validator
from sqlmodel import Session, col, select

from app.api.deps import SessionDep
from app.model_config.models import ModelConfig
from app.model_config.service import lock_owner
from app.training.boss import (
    FIRST_STAGE,
    BossDecision,
    FirstStage,
)
from app.training.boss_models import (
    BossAttempt,
    BossDisposition,
    BossPromotion,
    BossRevalidation,
)
from app.training.boss_service import decision_for, revalidations
from app.training.boss_stages import (
    STAGES,
    BossStage,
    ReleasedStage,
    StageDecision,
    parse_stage,
    stage_at_level,
)
from app.training.evaluation_models import Evaluation
from app.training.independent_models import IndependentWork
from app.training.independent_routes import enqueue
from app.training.models import TrainingRun
from app.training.review_service import points
from app.training.routes import TaskPublic, VerifiedUser, owned, view

router = APIRouter(prefix="/boss", tags=["boss"])


class RevalidationEventPublic(BaseModel):
    id: uuid.UUID
    sequence: int
    kind: str
    review_run_id: uuid.UUID | None
    resolved_run_id: uuid.UUID | None
    created_at: datetime


class RevalidationPublic(BaseModel):
    promotion_id: uuid.UUID
    original_run_id: uuid.UUID
    stage: ReleasedStage
    current_event_id: uuid.UUID
    status: str
    events: list[RevalidationEventPublic]


def revalidation_view(session: Session, item: BossRevalidation) -> RevalidationPublic:
    promotion = session.get(BossPromotion, item.promotion_id)
    assert promotion
    attempt = session.get(BossAttempt, promotion.run_id)
    assert attempt
    events = session.exec(
        select(BossRevalidation)
        .where(BossRevalidation.promotion_id == item.promotion_id)
        .order_by(col(BossRevalidation.sequence))
    ).all()
    return RevalidationPublic(
        promotion_id=promotion.id,
        original_run_id=promotion.run_id,
        stage=parse_stage(attempt.stage),
        current_event_id=item.id,
        status=item.kind,
        events=[
            RevalidationEventPublic.model_validate(e, from_attributes=True)
            for e in events
        ],
    )


class BossAccess(BaseModel):
    stage: ReleasedStage
    points: int
    level: str
    can_start: bool
    run_ids: list[uuid.UUID]
    revalidations: list[RevalidationPublic]


class BossStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID
    revalidation_of: uuid.UUID | None = None
    expected_revalidation_event_id: uuid.UUID | None = None
    expected_stage: ReleasedStage
    expected_config_version: uuid.UUID
    disclosure_accepted: bool

    @field_validator("expected_stage", mode="before")
    @classmethod
    def stage_from_json(cls, value: Any) -> ReleasedStage:
        if not isinstance(value, dict):
            raise ValueError("expected frozen stage object")
        return (
            FirstStage if value.get("version") == FIRST_STAGE.version else BossStage
        ).model_validate_json(json.dumps(value))


class BossPublic(BaseModel):
    run_id: uuid.UUID
    stage: ReleasedStage
    decision: BossDecision | StageDecision | None
    promotion_id: uuid.UUID | None
    revalidation_of: uuid.UUID | None
    revalidation: RevalidationPublic | None
    disposition: str | None
    launch_level: str
    current_level: str
    points: int


def points_for(session: SessionDep, user_id: uuid.UUID) -> int:
    return points(session, user_id)


@router.get("/access")
def boss_access(
    user: VerifiedUser, session: SessionDep, response: Response
) -> BossAccess:
    response.headers["Cache-Control"] = "no-store"
    lock_owner(session, user.id)
    session.refresh(user)
    points = points_for(session, user.id)
    runs = session.exec(
        select(TrainingRun.id)
        .join(BossAttempt, col(BossAttempt.run_id) == col(TrainingRun.id))
        .where(TrainingRun.user_id == user.id)
        .order_by(col(TrainingRun.created_at).desc())
    ).all()
    stage = stage_at_level(user.level)
    if stage is None:
        raise HTTPException(409, "当前等级无已发布挑战标准")
    return BossAccess(
        stage=stage,
        points=points,
        level=user.level,
        can_start=points >= stage.launch_points,
        run_ids=list(runs),
        revalidations=[
            revalidation_view(session, item) for item in revalidations(session, user.id)
        ],
    )


@router.post("/start", status_code=202)
def start_boss(
    body: BossStart, user: VerifiedUser, session: SessionDep, response: Response
) -> TaskPublic:
    response.headers["Cache-Control"] = "no-store"
    if body.expected_stage not in (FIRST_STAGE, *STAGES):
        raise HTTPException(409, "阶段标准已变化，请重新读取并确认全部必考范围")
    lock_owner(session, user.id)
    session.refresh(user)
    existing = session.get(TrainingRun, body.request_id)
    if existing:
        attempt = session.get(BossAttempt, existing.id)
        if (
            existing.user_id != user.id
            or not attempt
            or attempt.stage != body.expected_stage.model_dump(mode="json")
            or existing.config_version != body.expected_config_version
            or attempt.revalidation_of != body.revalidation_of
            or attempt.revalidation_event_id != body.expected_revalidation_event_id
        ):
            raise HTTPException(409, "该请求身份已用于其他挑战，请读取原记录")
        return view(session, existing)
    points = points_for(session, user.id)
    stage = stage_at_level(user.level)
    pending = revalidations(session, user.id, pending_only=True)
    if body.revalidation_of is not None:
        required = next(
            (item for item in pending if item.promotion_id == body.revalidation_of),
            None,
        )
        if not required or required.id != body.expected_revalidation_event_id:
            raise HTTPException(409, "该条补验要求已变化或不属于本人，请重新读取")
        promotion = session.get(BossPromotion, required.promotion_id)
        assert promotion
        original = session.get(BossAttempt, promotion.run_id)
        assert original
        stage = parse_stage(original.stage)
    elif body.expected_revalidation_event_id is not None:
        raise HTTPException(422, "请明确关联原晋级记录")
    if stage != body.expected_stage or points < body.expected_stage.launch_points:
        raise HTTPException(
            409,
            "当前阶段或累计修为未满足冻结标准；修为不自动晋升，也不要求刷完全部小关",
        )
    if not body.disclosure_accepted:
        raise HTTPException(422, "请先确认阶段标准、必考范围与模型目的地；重试可能计费")
    config = session.get(ModelConfig, user.id, populate_existing=True)
    if not config or config.revoked or config.version != body.expected_config_version:
        raise HTTPException(409, "当前模型配置不可用或已变更，请重新确认目的地")
    if session.exec(
        select(TrainingRun.id).where(
            TrainingRun.user_id == user.id,
            col(TrainingRun.status).in_(["queued", "running", "stopping"]),
        )
    ).first():
        raise HTTPException(409, "已有生成任务，请等待或停止后主动开始")
    run = TrainingRun(
        id=body.request_id,
        user_id=user.id,
        launch_mode="independent",
        config_version=config.version,
        destination=config.service_url,
        model_id=config.model_id,
        target=body.expected_stage.mandatory[0].target.model_dump(),
        selection={
            "entry": "boss",
            "catalog_version": body.expected_stage.catalog_version,
            "goal": "Boss："
            + "、".join(m.scope for m in body.expected_stage.mandatory),
        },
    )
    session.add(run)
    session.flush()
    session.add(
        BossAttempt(
            run_id=run.id,
            stage=body.expected_stage.model_dump(mode="json"),
            launch_points=points,
            launch_level=user.level,
            revalidation_of=body.revalidation_of,
            revalidation_event_id=body.expected_revalidation_event_id,
            promotion_blocked=bool(pending),
        )
    )
    session.add(IndependentWork(run_id=run.id))
    enqueue(session, run)
    session.commit()
    return view(session, run)


@router.get("/tasks/{run_id}")
def read_boss(
    run_id: uuid.UUID, user: VerifiedUser, session: SessionDep, response: Response
) -> BossPublic:
    response.headers["Cache-Control"] = "no-store"
    lock_owner(session, user.id)
    run = owned(session, run_id, user.id)
    attempt = session.get(BossAttempt, run.id)
    if not attempt:
        raise HTTPException(404, "不是Boss挑战")
    evaluation = session.get(Evaluation, run.id)
    result = decision_for(session, run, evaluation) if evaluation else None
    promotion = session.exec(
        select(BossPromotion).where(BossPromotion.run_id == run.id)
    ).first()
    session.refresh(user)
    associated = promotion.id if promotion else attempt.revalidation_of
    item = next(
        (
            row
            for row in revalidations(session, user.id)
            if row.promotion_id == associated
        ),
        None,
    )
    disposition = session.get(BossDisposition, run.id)
    return BossPublic(
        run_id=run.id,
        stage=parse_stage(attempt.stage),
        decision=result,
        promotion_id=promotion.id if promotion else None,
        revalidation_of=attempt.revalidation_of,
        revalidation=revalidation_view(session, item) if item else None,
        disposition=disposition.outcome if disposition else None,
        launch_level=attempt.launch_level,
        current_level=user.level,
        points=points_for(session, user.id),
    )
