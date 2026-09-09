"""Explicit new checks and voluntary practice conversion; no in-place promotion."""

import uuid

import procrastinate
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict
from sqlmodel import col, select

from app.api.deps import SessionDep
from app.model_config.models import ModelConfig
from app.model_config.service import lock_owner
from app.quality.rules import Binding
from app.quality.service import require_start
from app.training.draft_collection import lock_run
from app.training.evaluation_schema import EVALUATION_RULE
from app.training.events import next_event
from app.training.independent_models import IndependentWork
from app.training.models import TrainingRun
from app.training.queue import DSN
from app.training.routes import TaskPublic, VerifiedUser, owned, view
from app.training.schema import Source
from app.training.worker import generate_training

router = APIRouter(prefix="/training", tags=["independent"])


class CheckStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID
    expected_config_version: uuid.UUID
    disclosure_accepted: bool


def enqueue(session: SessionDep, run: TrainingRun) -> None:
    # Shared by replay-safe new checks, direct prerequisite checks, Boss and retry.
    # All callers already hold User; the gate commits with the queued run.
    if run.launch_mode == "independent":
        require_start(
            session,
            Binding(
                user_id=run.user_id,
                config_version=run.config_version,
                destination=run.destination,
                model_id=run.model_id,
                evaluation_rule=EVALUATION_RULE,
            ),
            [Source.model_validate(s) for s in run.sources] or None,
        )
    app = procrastinate.App(connector=procrastinate.SyncPsycopgConnector(conninfo=DSN))
    task = app.task(name="training.generate")(generate_training.func)
    run.queue_job_id = task.configure(
        connection=session.connection().connection.driver_connection, lock=str(run.id)
    ).defer(run_id=str(run.id))
    session.add(run)


@router.post("/tasks/{origin_id}/independent", status_code=202)
def start_check(
    origin_id: uuid.UUID,
    body: CheckStart,
    session: SessionDep,
    user: VerifiedUser,
    response: Response,
) -> TaskPublic:
    response.headers["Cache-Control"] = "no-store"
    origin = owned(session, origin_id, user.id)
    lock_owner(session, user.id)
    session.refresh(origin)
    existing = session.get(TrainingRun, body.request_id)
    if existing:
        if (
            existing.user_id != user.id
            or existing.origin_id != origin_id
            or existing.launch_mode != "independent"
        ):
            raise HTTPException(409, "新轮标识已使用；不能将原轮改为独立检验")
        return view(session, existing)
    if not body.disclosure_accepted:
        raise HTTPException(
            422,
            "请确认发送新旧情境及判据用于陌生比较；不发送旧作答或帮助全文，重试可能计费",
        )
    if not origin.candidate:
        raise HTTPException(409, "原轮尚无可用案例")
    if session.exec(
        select(TrainingRun.id).where(
            TrainingRun.user_id == user.id,
            col(TrainingRun.status).in_(["queued", "running", "stopping"]),
        )
    ).first():
        raise HTTPException(409, "已有生成任务，请等待或先停止；没有自动另开新轮")
    config = session.get(ModelConfig, user.id, populate_existing=True)
    if not config or config.revoked or config.version != body.expected_config_version:
        raise HTTPException(409, "模型配置已改变，请重新确认目的地")
    run = TrainingRun(
        id=body.request_id,
        user_id=user.id,
        launch_mode="independent",
        origin_id=origin.id,
        config_version=config.version,
        destination=config.service_url,
        model_id=config.model_id,
        selection=origin.selection.copy(),
        target=origin.target.copy(),
        sources=origin.sources.copy(),
        message="主动新建独立检验；正在生成并核对陌生情境",
    )
    session.add(run)
    session.flush()
    session.add(IndependentWork(run_id=run.id))
    enqueue(session, run)
    session.commit()
    return view(session, run)


@router.post("/tasks/{run_id}/practice")
def convert_practice(
    run_id: uuid.UUID, session: SessionDep, user: VerifiedUser, response: Response
) -> TaskPublic:
    response.headers["Cache-Control"] = "no-store"
    owned(session, run_id, user.id)
    lock_owner(session, user.id)
    run = lock_run(session, run_id)
    if run.launch_mode == "independent" and run.converted_sequence is None:
        run.converted_sequence = next_event(session, run_id)
        session.add(run)
        session.commit()
    return view(session, run)


@router.post("/tasks/{run_id}/independent/retry", status_code=202)
def retry_check(
    run_id: uuid.UUID, session: SessionDep, user: VerifiedUser, response: Response
) -> TaskPublic:
    response.headers["Cache-Control"] = "no-store"
    owned(session, run_id, user.id)
    lock_owner(session, user.id)
    run = lock_run(session, run_id)
    if run.status in {"queued", "running"}:
        return view(session, run)
    if (
        run.launch_mode != "independent"
        or run.candidate
        or run.status not in {"failed", "stopped"}
        or run.attempts >= 6
        or run.generation_attempts >= 3
        or run.code
        not in {
            "stopped",
            "cancelled",
            "unknown",
            "connection",
            "timeout",
            "rate_limited",
            "temporary_service",
            "dns",
            "unresolved_history_delivery",
            "internal_failure",
        }
    ):
        raise HTTPException(409, "本轮没有可恢复步骤或预算；可主动新建检验")
    config = session.get(ModelConfig, user.id, populate_existing=True)
    if not config or config.revoked or config.version != run.config_version:
        raise HTTPException(409, "旧配置已不可用；请确认新目的地并主动新建")
    run.status, run.stop_requested, run.code = "queued", False, "queued"
    enqueue(session, run)
    session.commit()
    return view(session, run)
