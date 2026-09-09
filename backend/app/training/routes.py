import random
import secrets
import uuid
from typing import Annotated

import procrastinate
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict
from sqlmodel import Session, col, select

from app.api.deps import SessionDep, get_training_user
from app.capabilities.catalog import CATALOG, EvidenceKey
from app.model_config.connection import Attempt
from app.model_config.models import ModelConfig
from app.model_config.service import lock_owner
from app.models import User
from app.training.models import TrainingAttempt, TrainingRun
from app.training.queue import DSN
from app.training.schema import Candidate, PublicCase, Source, public_case
from app.training.worker import generate_training

router = APIRouter(prefix="/training", tags=["training"])
VerifiedUser = Annotated[User, Depends(get_training_user)]


class Start(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disclosure_accepted: bool
    expected_config_version: uuid.UUID
    previous_run_id: uuid.UUID | None = None


class TaskPublic(BaseModel):
    id: uuid.UUID
    status: str
    code: str
    message: str
    config_version: uuid.UUID
    destination: str
    model_id: str
    target: EvidenceKey
    goal: str
    attempts: list[Attempt]
    case: PublicCase | None
    launch_mode: str
    current_mode: str
    origin_id: uuid.UUID | None
    independent_outcome: str | None


def owned(session: Session, run_id: uuid.UUID, user_id: uuid.UUID) -> TrainingRun:
    run = session.get(TrainingRun, run_id)
    if not run or run.user_id != user_id:
        raise HTTPException(404, "任务不存在")
    return run


def view(session: Session, run: TrainingRun) -> TaskPublic:
    from app.training.independent_models import IndependentObservation

    observation = session.exec(
        select(IndependentObservation)
        .where(
            IndependentObservation.run_id == run.id,
        )
        .order_by(col(IndependentObservation.sequence).desc())
    ).first()
    attempts = session.exec(
        select(TrainingAttempt)
        .where(TrainingAttempt.run_id == run.id)
        .order_by(col(TrainingAttempt.number))
    ).all()
    return TaskPublic(
        launch_mode=run.launch_mode,
        current_mode="practice"
        if run.converted_sequence is not None
        else run.launch_mode,
        origin_id=run.origin_id,
        independent_outcome=observation.outcome if observation else None,
        id=run.id,
        status=run.status,
        code=run.code,
        message=run.message,
        config_version=run.config_version,
        destination=run.destination,
        model_id=run.model_id,
        target=EvidenceKey.model_validate(run.target),
        goal=run.selection.get("goal", run.target["capability_id"]),
        attempts=[
            Attempt(
                number=a.number,
                code=a.code,
                prompt_tokens=a.prompt_tokens,
                completion_tokens=a.completion_tokens,
                total_tokens=a.total_tokens,
            )
            for a in attempts
        ],
        case=public_case(
            Candidate.model_validate(run.candidate),
            [Source.model_validate(s) for s in run.sources],
        )
        if run.candidate
        else None,
    )


@router.post("/random", status_code=202)
def start(
    body: Start, session: SessionDep, user: VerifiedUser, response: Response
) -> TaskPublic:
    response.headers["Cache-Control"] = "no-store"
    if not body.disclosure_accepted:
        raise HTTPException(422, "请确认本次资料发给已保存模型目的地及重试可能计费")
    lock_owner(session, user.id)
    active = session.exec(
        select(TrainingRun).where(
            TrainingRun.user_id == user.id,
            col(TrainingRun.status).in_(["queued", "running", "stopping"]),
        )
    ).first()
    if active:
        return view(session, active)
    config = session.get(ModelConfig, user.id)
    if not config or config.revoked:
        raise HTTPException(409, "请先保存模型配置")
    if config.version != body.expected_config_version:
        raise HTTPException(409, "模型目的地已变更，请刷新并确认本次接收方")
    if session.exec(
        select(TrainingRun.id).where(
            TrainingRun.user_id == user.id,
            col(TrainingRun.formal_submitted_at).is_not(None),
        )
    ).first():
        raise HTTPException(
            409, "已有正式作答；后续随机推荐由 T09 接续，本入口仅生成首关"
        )
    previous = (
        owned(session, body.previous_run_id, user.id) if body.previous_run_id else None
    )
    candidates = [
        EvidenceKey(
            capability_id=c.id,
            difficulty=level.difficulty,
            background_id=c.background_id,
        )
        for d in CATALOG.domains
        for c in d.capabilities
        for level in c.levels
        if level.difficulty == "基础"
        and level.satisfied_by(set())
        and (not previous or c.id != previous.target["capability_id"])
    ]
    if not candidates:
        raise HTTPException(409, "没有可用的基础无前置方向")
    seed = secrets.token_hex(32)
    target = random.Random(seed).choice(candidates)
    capability = next(
        c
        for d in CATALOG.domains
        for c in d.capabilities
        if c.id == target.capability_id
    )
    run = TrainingRun(
        user_id=user.id,
        config_version=config.version,
        destination=config.service_url,
        model_id=config.model_id,
        target=target.model_dump(),
        selection={
            "seed": seed,
            "catalog_version": CATALOG.version,
            "goal": capability.title,
            "candidates": [candidate.model_dump() for candidate in candidates],
        },
    )
    session.add(run)
    session.flush()
    # psycopg3's native connection shares this exact SQLAlchemy transaction.
    sync_queue = procrastinate.App(
        connector=procrastinate.SyncPsycopgConnector(conninfo=DSN)
    )
    task = sync_queue.task(name="training.generate")(generate_training.func)
    run.queue_job_id = task.configure(
        connection=session.connection().connection.driver_connection, lock=str(run.id)
    ).defer(run_id=str(run.id))
    session.add(run)
    session.commit()
    session.refresh(run)
    return view(session, run)


@router.get("/tasks")
def latest(
    session: SessionDep, user: VerifiedUser, response: Response
) -> list[TaskPublic]:
    response.headers["Cache-Control"] = "no-store"
    runs = session.exec(
        select(TrainingRun)
        .where(TrainingRun.user_id == user.id)
        .order_by(col(TrainingRun.created_at).desc())
        .limit(20)
    ).all()
    return [view(session, run) for run in runs]


@router.get("/tasks/{run_id}")
def read(
    run_id: uuid.UUID, session: SessionDep, user: VerifiedUser, response: Response
) -> TaskPublic:
    response.headers["Cache-Control"] = "no-store"
    return view(session, owned(session, run_id, user.id))


@router.post("/tasks/{run_id}/stop")
def stop(
    run_id: uuid.UUID, session: SessionDep, user: VerifiedUser, response: Response
) -> TaskPublic:
    response.headers["Cache-Control"] = "no-store"
    run = owned(session, run_id, user.id)
    # First persist intent without taking the credential lock. The worker's async
    # cancellation path can see this while an in-flight request holds User.
    run = session.exec(
        select(TrainingRun)
        .where(TrainingRun.id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    if run.status in {"completed", "failed", "stopped"}:
        return view(session, run)
    run.stop_requested, run.status = True, "stopping"
    job_id = run.queue_job_id
    session.add(run)
    session.commit()
    with procrastinate.App(
        connector=procrastinate.SyncPsycopgConnector(conninfo=DSN)
    ).open() as app:
        if job_id is not None:
            app.job_manager.cancel_job_by_id(job_id, abort=True)
    # Success is serialized after the real HTTP invocation releases its lock;
    # recording intent is not advertised as an already-effective stop.
    from app.training.worker import finish_stop

    finish_stop(run_id, job_id)
    session.refresh(run)
    return view(session, run)
