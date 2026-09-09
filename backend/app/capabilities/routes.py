import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict
from sqlmodel import col, select

from app.api.deps import SessionDep, get_training_user
from app.capabilities.catalog import CATALOG, Catalog, EvidenceKey
from app.capabilities.evidence import EvidenceMap
from app.capabilities.evidence_service import read_evidence
from app.capabilities.unlocks import UnitAccess, level_for, open_unit, read_access
from app.model_config.models import ModelConfig
from app.model_config.service import lock_owner
from app.models import User
from app.training.independent_models import IndependentWork
from app.training.independent_routes import enqueue
from app.training.models import TrainingRun
from app.training.routes import TaskPublic, view

router = APIRouter(prefix="/capabilities", tags=["capabilities"])


@router.get("/catalog", response_model=Catalog)
def read_catalog(
    _user: Annotated[User, Depends(get_training_user)], response: Response
) -> Catalog:
    response.headers["Cache-Control"] = "no-store"
    return CATALOG


@router.get("/evidence", response_model=EvidenceMap)
def read_capability_evidence(
    user: Annotated[User, Depends(get_training_user)],
    session: SessionDep,
    response: Response,
) -> EvidenceMap:
    response.headers["Cache-Control"] = "no-store"
    lock_owner(session, user.id)
    return read_evidence(session, user.id)


class UnitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: EvidenceKey
    catalog_version: str


@router.get("/access")
def read_units(
    user: Annotated[User, Depends(get_training_user)],
    session: SessionDep,
    response: Response,
) -> list[UnitAccess]:
    response.headers["Cache-Control"] = "no-store"
    lock_owner(session, user.id)
    return read_access(session, user.id)


@router.post("/open")
def open_learning_unit(
    body: UnitRequest,
    user: Annotated[User, Depends(get_training_user)],
    session: SessionDep,
    response: Response,
) -> UnitAccess:
    response.headers["Cache-Control"] = "no-store"
    if body.catalog_version != CATALOG.version:
        raise HTTPException(409, "能力目录已变化，请重新读取原目标与真实前置")
    lock_owner(session, user.id)
    result = open_unit(session, user.id, body.target)
    session.commit()
    return result


class TargetStart(UnitRequest):
    request_id: uuid.UUID
    expected_config_version: uuid.UUID
    disclosure_accepted: bool
    mode: Literal["practice", "independent"]
    return_target: EvidenceKey | None = None


@router.post("/start", status_code=202)
def start_target(
    body: TargetStart,
    user: Annotated[User, Depends(get_training_user)],
    session: SessionDep,
    response: Response,
) -> TaskPublic:
    response.headers["Cache-Control"] = "no-store"
    if body.catalog_version != CATALOG.version:
        raise HTTPException(409, "目录已变化，请重新确认目标；没有自动降低难度")
    level_for(body.target)
    if body.return_target:
        level_for(body.return_target)
    lock_owner(session, user.id)
    existing = session.get(TrainingRun, body.request_id)
    if existing:
        if (
            existing.user_id != user.id
            or existing.target != body.target.model_dump()
            or existing.launch_mode != body.mode
            or existing.config_version != body.expected_config_version
            or existing.selection.get("return_target")
            != (body.return_target.model_dump() if body.return_target else None)
        ):
            raise HTTPException(409, "请求身份已用于另一目标；请读取原记录")
        return view(session, existing)
    if not body.disclosure_accepted:
        raise HTTPException(422, "请确认目标、模型接收方和必要资料；重试可能计费")
    config = session.get(ModelConfig, user.id, populate_existing=True)
    if not config or config.revoked or config.version != body.expected_config_version:
        raise HTTPException(
            409, "模型配置不可用或已变更；不是前置能力不足，请重新确认目的地"
        )
    if session.exec(
        select(TrainingRun.id).where(
            TrainingRun.user_id == user.id,
            col(TrainingRun.status).in_(["queued", "running", "stopping"]),
        )
    ).first():
        raise HTTPException(409, "已有生成任务，请等待或停止后主动开始")
    # A direct independent check can establish missing proof without first
    # revealing a practice answer. It never grants a prerequisite opening.
    if body.mode == "practice":
        open_unit(session, user.id, body.target)
    capability = next(
        c
        for d in CATALOG.domains
        for c in d.capabilities
        if c.id == body.target.capability_id
    )
    run = TrainingRun(
        id=body.request_id,
        user_id=user.id,
        launch_mode=body.mode,
        config_version=config.version,
        destination=config.service_url,
        model_id=config.model_id,
        target=body.target.model_dump(),
        selection={
            "catalog_version": CATALOG.version,
            "goal": capability.title,
            "entry": "prerequisite_target",
            "return_target": body.return_target.model_dump()
            if body.return_target
            else None,
        },
    )
    session.add(run)
    session.flush()
    if body.mode == "independent":
        session.add(IndependentWork(run_id=run.id))
    enqueue(session, run)
    session.commit()
    return view(session, run)
