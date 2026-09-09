"""Owner-only review acceptance, explicit resumption and readable audit history."""

import uuid
from datetime import datetime

import procrastinate
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.api.deps import SessionDep
from app.model_config.models import ModelConfig
from app.model_config.output import check_output
from app.model_config.service import decrypt, lock_owner
from app.training.evaluation_models import Evaluation
from app.training.queue import DSN
from app.training.review_models import ReviewAttempt, ScoreReview
from app.training.review_rules import Opinion
from app.training.review_service import snapshot_for
from app.training.review_worker import ACTIVE, RETRYABLE, context, finish, review_score
from app.training.routes import VerifiedUser, owned

router = APIRouter(prefix="/training", tags=["reviews"])


class ReviewStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID
    disclosure_accepted: bool
    expected_config_version: uuid.UUID


class ReviewResume(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disclosure_accepted: bool
    expected_config_version: uuid.UUID


class ReviewCall(BaseModel):
    number: int
    config_version: uuid.UUID
    destination: str
    model_id: str
    code: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None


class ReviewPublic(BaseModel):
    grading_quality: str = "unverified"
    run_id: uuid.UUID
    request_id: uuid.UUID
    decision: str
    status: str
    code: str
    message: str
    config_version: uuid.UUID
    destination: str
    model_id: str
    accepted_at: datetime
    opinion: Opinion | None
    attempts: list[ReviewCall]
    remaining_attempts: int


def view(session: Session, item: ScoreReview) -> ReviewPublic:
    session.refresh(item)
    from app.quality.models import QualityDisposition

    quality = session.get(QualityDisposition, (item.run_id, "review"))
    return ReviewPublic(
        grading_quality=quality.status if quality else "unverified",
        **item.model_dump(
            exclude={
                "snapshot",
                "opinion",
                "attempts",
                "attempt_limit",
                "queue_job_id",
                "stop_requested",
            }
        ),
        opinion=Opinion.model_validate(item.opinion) if item.opinion else None,
        attempts=[
            ReviewCall.model_validate(a.model_dump())
            for a in session.exec(
                select(ReviewAttempt)
                .where(ReviewAttempt.run_id == item.run_id)
                .order_by(col(ReviewAttempt.number))
            ).all()
        ],
        remaining_attempts=max(0, 6 - item.attempts),
    )


def configuration(
    session: Session, user_id: uuid.UUID, body: ReviewResume | ReviewStart
) -> ModelConfig:
    if not body.disclosure_accepted:
        raise HTTPException(
            422,
            "请确认发送冻结原题、来源、原答及许可澄清、原评分至所示模型；重试可能计费",
        )
    config = session.get(ModelConfig, user_id, populate_existing=True)
    if not config or config.revoked or config.version != body.expected_config_version:
        raise HTTPException(409, "配置已变更，请核对当前复核目的地后重新确认")
    return config


def enqueue(session: Session, item: ScoreReview) -> None:
    app = procrastinate.App(connector=procrastinate.SyncPsycopgConnector(conninfo=DSN))
    task = app.task(name="training.review")(review_score.func)
    item.queue_job_id = task.configure(
        connection=session.connection().connection.driver_connection,
        lock="review:" + str(item.run_id),
    ).defer(run_id=str(item.run_id))
    session.add(item)


@router.get("/tasks/{run_id}/review")
def read_review(
    run_id: uuid.UUID, session: SessionDep, user: VerifiedUser, response: Response
) -> ReviewPublic | None:
    response.headers["Cache-Control"] = "no-store"
    owned(session, run_id, user.id)
    item = session.get(ScoreReview, run_id)
    return view(session, item) if item else None


@router.post("/tasks/{run_id}/review", status_code=202)
def start_review(
    run_id: uuid.UUID,
    body: ReviewStart,
    session: SessionDep,
    user: VerifiedUser,
    response: Response,
) -> ReviewPublic:
    response.headers["Cache-Control"] = "no-store"
    run = owned(session, run_id, user.id)
    lock_owner(session, user.id)
    session.refresh(run)
    existing = session.get(ScoreReview, run_id, populate_existing=True)
    if existing:
        if existing.request_id != body.request_id:
            raise HTTPException(
                409, "本次评分已受理过复核，请读取已有复核；不会开启第二次"
            )
        return view(session, existing)
    evaluation = session.get(Evaluation, run_id)
    if not evaluation:
        raise HTTPException(409, "本次尚无冻结评分")
    snapshot = snapshot_for(session, run, evaluation)
    config = configuration(session, user.id, body)
    item = ScoreReview(
        run_id=run_id,
        request_id=body.request_id,
        snapshot=snapshot.model_dump(mode="json"),
        config_version=config.version,
        destination=config.service_url,
        model_id=config.model_id,
    )
    try:
        import json

        check_output(
            json.dumps(context(item), ensure_ascii=False),
            decrypt(config).get_secret_value(),
        )
    except ValueError:
        raise HTTPException(
            422, "冻结输入疑似含秘密或无法核对；未受理、未发送"
        ) from None
    try:
        session.add(item)
        session.flush()
        enqueue(session, item)
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            409, "复核身份已经使用，请读取已有记录；未重复受理"
        ) from None
    return view(session, item)


@router.post("/tasks/{run_id}/review/retry", status_code=202)
def retry_review(
    run_id: uuid.UUID,
    body: ReviewResume,
    session: SessionDep,
    user: VerifiedUser,
    response: Response,
) -> ReviewPublic:
    response.headers["Cache-Control"] = "no-store"
    owned(session, run_id, user.id)
    lock_owner(session, user.id)
    item = session.exec(
        select(ScoreReview)
        .where(ScoreReview.run_id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one_or_none()
    if not item:
        raise HTTPException(404, "复核不存在")
    if item.status in ACTIVE or item.decision != "pending":
        return view(session, item)
    if item.status == "stopping" or item.attempts >= 6:
        raise HTTPException(409, "请等待停止完成或剩余预算已用完；原答与记录保留")
    config = configuration(session, user.id, body)
    last = session.exec(
        select(ReviewAttempt)
        .where(ReviewAttempt.run_id == run_id)
        .order_by(col(ReviewAttempt.number).desc())
    ).first()
    if last and last.config_version == config.version and last.code not in RETRYABLE:
        raise HTTPException(409, "当前配置下已有不可重试的失败结论；不会重复付费调用")
    item.config_version, item.destination, item.model_id = (
        config.version,
        config.service_url,
        config.model_id,
    )
    item.status, item.code, item.message = (
        "queued",
        "queued",
        "正在恢复同一复核；原输入、历史用量和累计预算不重置",
    )
    item.stop_requested = False
    item.attempt_limit = min(6, item.attempts + 3)
    enqueue(session, item)
    session.commit()
    return view(session, item)


@router.post("/tasks/{run_id}/review/stop")
def stop_review(
    run_id: uuid.UUID, session: SessionDep, user: VerifiedUser, response: Response
) -> ReviewPublic:
    response.headers["Cache-Control"] = "no-store"
    owned(session, run_id, user.id)
    item = session.exec(
        select(ScoreReview).where(ScoreReview.run_id == run_id).with_for_update()
    ).one_or_none()
    if not item:
        raise HTTPException(404, "复核不存在")
    if item.status not in ACTIVE | {"stopping"}:
        return view(session, item)
    job_id = item.queue_job_id
    item.stop_requested, item.status = True, "stopping"
    session.add(item)
    session.commit()
    with procrastinate.App(
        connector=procrastinate.SyncPsycopgConnector(conninfo=DSN)
    ).open() as app:
        if job_id is not None:
            app.job_manager.cancel_job_by_id(job_id, abort=True)
    # Stop intent commits before waiting for the User held by an in-flight call.
    lock_owner(session, user.id)
    session.commit()
    finish(
        run_id,
        job_id,
        "stopped",
        "已停止复核；仍待完成，原答与奖励保留，在途费用不保证撤回",
        require_stop=True,
    )
    return view(session, item)
