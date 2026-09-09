import secrets
import uuid
from datetime import UTC, datetime
from typing import Annotated, cast

import procrastinate
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func
from sqlmodel import Session, col, select

from app.api.deps import SessionDep, get_training_user
from app.capabilities.catalog import CATALOG, EvidenceKey
from app.capabilities.evidence_models import OriginalOrder
from app.capabilities.evidence_service import read_evidence
from app.capabilities.unlocks import read_access
from app.model_config.connection import Attempt
from app.model_config.models import ModelConfig
from app.model_config.service import lock_owner
from app.models import User
from app.training.models import TrainingAttempt, TrainingRun
from app.training.preference_models import RandomPreference
from app.training.queue import DSN
from app.training.recommendations import RULE, Preference, choose
from app.training.schema import Candidate, PublicCase, Source, public_case
from app.training.worker import generate_training

router = APIRouter(prefix="/training", tags=["training"])
VerifiedUser = Annotated[User, Depends(get_training_user)]


class Start(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disclosure_accepted: bool
    expected_config_version: uuid.UUID
    previous_run_id: uuid.UUID | None = None
    request_id: uuid.UUID | None = None
    expected_preference_version: uuid.UUID | None = None


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
    return_target: EvidenceKey | None = None
    recommendation_reason: str | None = None
    random_mode: str | None = None


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
        recommendation_reason=run.selection.get("reason"),
        random_mode=run.selection.get("random_mode"),
        return_target=EvidenceKey.model_validate(run.selection["return_target"])
        if run.selection.get("return_target")
        else None,
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


class PreferencePublic(BaseModel):
    version: uuid.UUID | None
    mode: Preference
    has_record: bool


class PreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: uuid.UUID | None
    mode: Preference


def has_formal_record(session: Session, user_id: uuid.UUID) -> bool:
    return (
        session.exec(
            # Written with the committed original answer, before relevance or
            # reward settlement. Its source excludes guided-practice answers.
            select(OriginalOrder.original_id).where(OriginalOrder.user_id == user_id)
        ).first()
        is not None
    )


@router.get("/random-preference")
def read_preference(
    session: SessionDep, user: VerifiedUser, response: Response
) -> PreferencePublic:
    response.headers["Cache-Control"] = "no-store"
    lock_owner(session, user.id)
    preference = session.get(RandomPreference, user.id)
    return PreferencePublic(
        version=preference.version if preference else None,
        mode=cast(Preference, preference.mode) if preference else "recommended",
        has_record=has_formal_record(session, user.id),
    )


@router.put("/random-preference")
def save_preference(
    body: PreferenceUpdate, session: SessionDep, user: VerifiedUser, response: Response
) -> PreferencePublic:
    response.headers["Cache-Control"] = "no-store"
    lock_owner(session, user.id)
    preference = session.get(RandomPreference, user.id)
    if (preference.version if preference else None) != body.expected_version:
        raise HTTPException(
            409, "另一设备已改变难度偏好，请重读后重新选择；未覆盖当前题目"
        )
    if not has_formal_record(session, user.id):
        raise HTTPException(409, "尚无正式作答，首次随机练习保持基础无前置起点")
    preference = preference or RandomPreference(user_id=user.id)
    preference.mode, preference.version = body.mode, uuid.uuid4()
    session.add(preference)
    session.commit()
    return PreferencePublic(version=preference.version, mode=body.mode, has_record=True)


@router.post("/random", status_code=202)
def start(
    body: Start, session: SessionDep, user: VerifiedUser, response: Response
) -> TaskPublic:
    response.headers["Cache-Control"] = "no-store"
    if not body.disclosure_accepted:
        raise HTTPException(422, "请确认本次资料发给已保存模型目的地及重试可能计费")
    lock_owner(session, user.id)
    if body.request_id:
        existing = session.get(TrainingRun, body.request_id)
        if existing:
            if (
                existing.user_id != user.id
                or existing.selection.get("entry") != "random"
                or existing.config_version != body.expected_config_version
                or existing.selection.get("preference_version")
                != (
                    str(body.expected_preference_version)
                    if body.expected_preference_version
                    else None
                )
                or existing.selection.get("previous_run_id")
                != (str(body.previous_run_id) if body.previous_run_id else None)
            ):
                raise HTTPException(409, "请求身份已用于另一随机任务，请读取原记录")
            return view(session, existing)
    active = session.exec(
        select(TrainingRun).where(
            TrainingRun.user_id == user.id,
            col(TrainingRun.status).in_(["queued", "running", "stopping"]),
        )
    ).first()
    if active:
        if body.request_id:
            raise HTTPException(409, "已有生成任务，请等待或停止后主动开始")
        return view(session, active)
    config = session.get(ModelConfig, user.id)
    if not config or config.revoked:
        raise HTTPException(409, "请先保存模型配置")
    if config.version != body.expected_config_version:
        raise HTTPException(409, "模型目的地已变更，请刷新并确认本次接收方")
    has_record = has_formal_record(session, user.id)
    preference = session.get(RandomPreference, user.id)
    if (preference.version if preference else None) != body.expected_preference_version:
        raise HTTPException(409, "难度偏好已变化，请重新读取并明确选择；当前题目不变")
    mode: Preference = (
        cast(Preference, preference.mode) if preference else "recommended"
    )
    previous = (
        owned(session, body.previous_run_id, user.id) if body.previous_run_id else None
    )
    delivered = session.exec(
        select(func.count())
        .select_from(TrainingRun)
        .where(
            TrainingRun.user_id == user.id,
            col(TrainingRun.recommendation_delivered_at).is_not(None),
        )
    ).one()
    now = datetime.now(UTC)
    seed = secrets.token_hex(32)
    # ponytail: full historical projections plus per-owner aggregate; measure
    # large-account latency before adding indexed projections/caches, never cap history.
    units = read_access(session, user.id)
    selection = choose(
        units=units,
        evidence=read_evidence(session, user.id),
        preference=mode,
        has_record=has_record,
        delivered=delivered,
        now=now,
        seed=seed,
        previous_capability=previous.target["capability_id"] if previous else None,
    )
    target = selection.target
    if target is None:
        raise HTTPException(
            409,
            {
                "message": "当前方向和难度没有可用目标；请改方向、明确调整难度，或选择缺项补练/检验。未自动降档。",
                "reason": selection.reason,
                "excluded": selection.excluded,
                "access": [
                    unit.model_dump(mode="json")
                    for unit in units
                    if (not has_record and unit.target.difficulty == "基础")
                    or (
                        has_record
                        and (mode == "recommended" or unit.target.difficulty == mode)
                    )
                ],
            },
        )
    capability = next(
        c
        for d in CATALOG.domains
        for c in d.capabilities
        if c.id == target.capability_id
    )
    # The explicit random entry selected this eligible published unit.
    # Persist in this SAME owner transaction (not the worker's separate HTTP
    # permission transaction, whose User lock would block the opening FK).
    from app.capabilities.unlocks import open_unit

    open_unit(session, user.id, target)
    run = TrainingRun(
        id=body.request_id or uuid.uuid4(),
        user_id=user.id,
        config_version=config.version,
        destination=config.service_url,
        model_id=config.model_id,
        target=target.model_dump(),
        selection={
            "entry": "random",
            "rule_version": RULE,
            "random_mode": "first" if not has_record else mode,
            "preference_version": str(body.expected_preference_version)
            if body.expected_preference_version
            else None,
            "previous_run_id": str(body.previous_run_id)
            if body.previous_run_id
            else None,
            "delivered_before": delivered,
            "selected_at": now.isoformat(),
            "reason": selection.reason,
            "excluded": selection.excluded,
            "seed": seed,
            "catalog_version": CATALOG.version,
            "goal": capability.title,
            "candidates": [
                candidate.model_dump() for candidate in selection.candidates
            ],
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
