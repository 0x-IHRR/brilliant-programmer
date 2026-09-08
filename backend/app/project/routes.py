import uuid
from typing import Annotated

import procrastinate
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlmodel import Session, col, select

from app.api.deps import SessionDep, get_training_user
from app.model_config.connection import Attempt
from app.model_config.models import ModelConfig
from app.model_config.service import lock_owner
from app.models import User
from app.project.github import parse_url
from app.project.models import ProjectAttempt, ProjectRun
from app.project.schema import ProjectMap, Snapshot
from app.project.worker import RETRYABLE, analyze_project
from app.training.queue import DSN

router = APIRouter(prefix="/projects", tags=["projects"])
VerifiedUser = Annotated[User, Depends(get_training_user)]


class ProjectStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(max_length=2048)
    disclosure_accepted: bool
    expected_config_version: uuid.UUID
    reanalyze: bool = False

    @field_validator("url")
    @classmethod
    def github_url(cls, value: str) -> str:
        parse_url(value)
        return value


class ProjectPublic(BaseModel):
    id: uuid.UUID
    url: str
    status: str
    code: str
    message: str
    config_version: uuid.UUID
    destination: str
    model_id: str
    reused_from_id: uuid.UUID | None
    snapshot: Snapshot | None
    project_map: ProjectMap | None
    attempts: list[Attempt]


def owned(session: Session, identity: uuid.UUID, user_id: uuid.UUID) -> ProjectRun:
    run = session.get(ProjectRun, identity)
    if not run or run.user_id != user_id:
        raise HTTPException(404, "项目任务不存在")
    return run


def view(session: Session, run: ProjectRun) -> ProjectPublic:
    attempts = session.exec(
        select(ProjectAttempt)
        .where(ProjectAttempt.run_id == run.id)
        .order_by(col(ProjectAttempt.number))
    ).all()
    return ProjectPublic(
        id=run.id,
        url=run.url,
        status=run.status,
        code=run.code,
        message=run.message,
        config_version=run.config_version,
        destination=run.destination,
        model_id=run.model_id,
        reused_from_id=run.reused_from_id,
        snapshot=Snapshot.model_validate(run.snapshot) if run.snapshot else None,
        project_map=ProjectMap.model_validate(run.project_map)
        if run.project_map
        else None,
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
    )


def enqueue(session: Session, run: ProjectRun) -> None:
    app = procrastinate.App(connector=procrastinate.SyncPsycopgConnector(conninfo=DSN))
    task = app.task(name="project.analyze")(analyze_project.func)
    run.queue_job_id = task.configure(
        connection=session.connection().connection.driver_connection, lock=str(run.id)
    ).defer(run_id=str(run.id))
    session.add(run)


@router.post("", status_code=202)
def start_project(
    body: ProjectStart, session: SessionDep, user: VerifiedUser, response: Response
) -> ProjectPublic:
    response.headers["Cache-Control"] = "no-store"
    if not body.disclosure_accepted:
        raise HTTPException(422, "请确认本次公开资料目的地与重试可能计费")
    lock_owner(session, user.id)
    config = session.get(ModelConfig, user.id)
    if not config or config.version != body.expected_config_version:
        raise HTTPException(409, "模型配置缺失或已变更，请读取并确认已保存目的地")
    active = session.exec(
        select(ProjectRun).where(
            ProjectRun.user_id == user.id,
            col(ProjectRun.status).in_(["queued", "running", "stopping"]),
        )
    ).first()
    if active:
        if active.url != body.url:
            raise HTTPException(409, "已有进行中的项目分析，请查看或停止该任务后再开始")
        return view(session, active)
    run = ProjectRun(
        user_id=user.id,
        url=body.url,
        reanalyze=body.reanalyze,
        config_version=config.version,
        destination=config.service_url,
        model_id=config.model_id,
    )
    session.add(run)
    session.flush()
    enqueue(session, run)
    session.commit()
    session.refresh(run)
    return view(session, run)


@router.get("")
def latest_projects(
    session: SessionDep, user: VerifiedUser, response: Response
) -> list[ProjectPublic]:
    response.headers["Cache-Control"] = "no-store"
    runs = session.exec(
        select(ProjectRun)
        .where(ProjectRun.user_id == user.id)
        .order_by(col(ProjectRun.created_at).desc())
        .limit(20)
    ).all()
    return [view(session, run) for run in runs]


@router.get("/{run_id}")
def read_project(
    run_id: uuid.UUID, session: SessionDep, user: VerifiedUser, response: Response
) -> ProjectPublic:
    response.headers["Cache-Control"] = "no-store"
    return view(session, owned(session, run_id, user.id))


@router.post("/{run_id}/retry", status_code=202)
def retry_project(
    run_id: uuid.UUID, session: SessionDep, user: VerifiedUser, response: Response
) -> ProjectPublic:
    response.headers["Cache-Control"] = "no-store"
    owned(session, run_id, user.id)
    lock_owner(session, user.id)
    run = owned(session, run_id, user.id)
    session.refresh(run)
    if run.status in {"queued", "running", "completed"}:
        return view(session, run)
    if (
        run.status != "failed"
        or run.attempts >= 6
        or run.generation_attempts >= 3
        or run.code not in RETRYABLE | {"internal_failure"}
    ):
        raise HTTPException(
            409, "本轮不可继续重试或预算已耗尽；停止代表本轮结束，可主动重分析新一轮"
        )
    config = session.get(ModelConfig, user.id)
    if not config or config.version != run.config_version:
        raise HTTPException(409, "配置已变更，请确认新配置后主动重分析")
    active = session.exec(
        select(ProjectRun.id).where(
            ProjectRun.user_id == user.id,
            col(ProjectRun.status).in_(["queued", "running", "stopping"]),
        )
    ).first()
    if active:
        raise HTTPException(409, "已有进行中的项目分析，请先查看实际状态")
    run.status, run.code, run.message = (
        "queued",
        "queued",
        "已主动重试同一任务；固定版本、成果与原尝试预算保留",
    )
    enqueue(session, run)
    session.commit()
    session.refresh(run)
    return view(session, run)


@router.post("/{run_id}/stop")
def stop_project(
    run_id: uuid.UUID, session: SessionDep, user: VerifiedUser, response: Response
) -> ProjectPublic:
    response.headers["Cache-Control"] = "no-store"
    owned(session, run_id, user.id)
    run = session.exec(
        select(ProjectRun)
        .where(ProjectRun.id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    if run.status in {"completed", "failed", "stopped"}:
        return view(session, run)
    run.stop_requested, run.status = True, "stopping"
    session.add(run)
    session.commit()
    with procrastinate.App(
        connector=procrastinate.SyncPsycopgConnector(conninfo=DSN)
    ).open() as app:
        if run.queue_job_id is not None:
            app.job_manager.cancel_job_by_id(run.queue_job_id, abort=True)
    lock_owner(session, user.id)
    session.refresh(run)
    run.status, run.code, run.message = (
        "stopped",
        "stopped",
        "本轮后续模型调用已停止，已核对成果保留；已尝试中断在途请求，不保证撤销或退款",
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return view(session, run)
