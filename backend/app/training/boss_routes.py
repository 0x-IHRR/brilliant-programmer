"""Owner-scoped first Boss admission; points permit starting, never promotion."""

import json
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import func
from sqlmodel import col, select

from app.api.deps import SessionDep
from app.model_config.models import ModelConfig
from app.model_config.service import lock_owner
from app.training.boss import (
    FIRST_STAGE,
    BossDecision,
    FirstStage,
    can_launch_first_boss,
)
from app.training.boss_models import BossAttempt, BossPromotion
from app.training.boss_service import decision_for
from app.training.evaluation_models import Evaluation
from app.training.independent_models import IndependentWork
from app.training.independent_routes import enqueue
from app.training.models import TrainingRun
from app.training.routes import TaskPublic, VerifiedUser, owned, view
from app.training.submission_models import PracticeAward

router = APIRouter(prefix="/boss", tags=["boss"])


class BossAccess(BaseModel):
    stage: FirstStage
    points: int
    level: str
    can_start: bool
    run_ids: list[uuid.UUID]


class BossStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID
    expected_stage: FirstStage
    expected_config_version: uuid.UUID
    disclosure_accepted: bool

    @field_validator("expected_stage", mode="before")
    @classmethod
    def stage_from_json(cls, value: Any) -> FirstStage:
        return FirstStage.model_validate_json(json.dumps(value))


class BossPublic(BaseModel):
    run_id: uuid.UUID
    stage: FirstStage
    decision: BossDecision | None
    promotion_id: uuid.UUID | None
    current_level: str
    points: int


def points_for(session: SessionDep, user_id: uuid.UUID) -> int:
    return session.exec(
        select(func.coalesce(func.sum(PracticeAward.points), 0)).where(
            PracticeAward.user_id == user_id
        )
    ).one()


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
    return BossAccess(
        stage=FIRST_STAGE,
        points=points,
        level=user.level,
        can_start=can_launch_first_boss(points, user.level),
        run_ids=list(runs),
    )


@router.post("/start", status_code=202)
def start_boss(
    body: BossStart, user: VerifiedUser, session: SessionDep, response: Response
) -> TaskPublic:
    response.headers["Cache-Control"] = "no-store"
    if body.expected_stage != FIRST_STAGE:
        raise HTTPException(409, "阶段标准已变化，请重新读取并确认三个必考范围")
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
        ):
            raise HTTPException(409, "该请求身份已用于其他挑战，请读取原记录")
        return view(session, existing)
    points = points_for(session, user.id)
    if not can_launch_first_boss(points, user.level):
        raise HTTPException(
            409, "首阶段Boss需小白阶段累计100点；修为不自动晋升，也不要求刷完全部小关"
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
        target=FIRST_STAGE.mandatory[0].target.model_dump(),
        selection={
            "entry": "first_boss",
            "catalog_version": FIRST_STAGE.catalog_version,
            "goal": "首阶段Boss：请求链路、局部因果与查证验证",
        },
    )
    session.add(run)
    session.flush()
    session.add(
        BossAttempt(
            run_id=run.id,
            stage=FIRST_STAGE.model_dump(mode="json"),
            launch_points=points,
            launch_level=user.level,
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
        raise HTTPException(404, "不是首阶段Boss")
    evaluation = session.get(Evaluation, run.id)
    result = decision_for(session, run, evaluation) if evaluation else None
    promotion = session.exec(
        select(BossPromotion).where(BossPromotion.run_id == run.id)
    ).first()
    session.refresh(user)
    return BossPublic(
        run_id=run.id,
        stage=FIRST_STAGE,
        decision=result,
        promotion_id=promotion.id if promotion else None,
        current_level=user.level,
        points=points_for(session, user.id),
    )
