import hashlib
import json
import uuid

import procrastinate
from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import func
from sqlmodel import Session, col, select

from app.api.deps import SessionDep
from app.model_config.connection import Attempt
from app.model_config.models import ModelConfig
from app.model_config.service import decrypt, lock_owner
from app.training.draft_collection import submit_guard
from app.training.evaluation_models import Evaluation
from app.training.events import next_event
from app.training.queue import DSN
from app.training.routes import VerifiedUser, owned
from app.training.schema import Candidate
from app.training.sources import contains_secret
from app.training.submission_models import PracticeAward, Submission, SubmissionAttempt
from app.training.submission_schema import (
    SubmissionPublic,
    SubmissionState,
    Submit,
    validate_answers,
)
from app.training.submission_worker import (
    RETRYABLE,
    check_submission,
    finish_submission_stop,
)

router = APIRouter(prefix="/training", tags=["submissions"])


def enqueue(session: Session, submission: Submission) -> None:
    app = procrastinate.App(connector=procrastinate.SyncPsycopgConnector(conninfo=DSN))
    task = app.task(name="training.check_submission")(check_submission.func)
    submission.queue_job_id = task.configure(
        connection=session.connection().connection.driver_connection,
        lock=str(submission.id),
    ).defer(submission_id=str(submission.id))
    session.add(submission)


def state(
    session: Session,
    run_id: uuid.UUID,
    user_id: uuid.UUID,
    practice_help_id: uuid.UUID | None = None,
) -> SubmissionState:
    run = owned(session, run_id, user_id)
    submissions = session.exec(
        select(Submission)
        .where(
            Submission.run_id == run_id, Submission.practice_help_id == practice_help_id
        )
        .order_by(col(Submission.sequence))
    ).all()
    award = session.get(PracticeAward, run_id)
    return SubmissionState(
        run_id=run_id,
        completed_at=run.formal_submitted_at if practice_help_id is None else None,
        awarded_points=award.points if award else 0,
        total_points=session.exec(
            select(func.coalesce(func.sum(PracticeAward.points), 0)).where(
                PracticeAward.user_id == user_id
            )
        ).one(),
        rule_version=award.rule_version if award else None,
        submissions=[
            SubmissionPublic(
                **s.model_dump(
                    exclude={
                        "attempts",
                        "input_hash",
                        "attempt_limit",
                        "queue_job_id",
                        "run_id",
                        "stop_requested",
                    }
                ),
                attempts=[
                    Attempt(
                        number=a.number,
                        code=a.code,
                        prompt_tokens=a.prompt_tokens,
                        completion_tokens=a.completion_tokens,
                        total_tokens=a.total_tokens,
                    )
                    for a in session.exec(
                        select(SubmissionAttempt)
                        .where(SubmissionAttempt.submission_id == s.id)
                        .order_by(col(SubmissionAttempt.number))
                    ).all()
                ],
                can_retry=s.status in {"failed", "stopped"}
                and s.attempts < 6
                and s.code
                in RETRYABLE | {"budget_exhausted", "stopped", "internal_failure"},
            )
            for s in submissions
        ],
    )


@router.get("/tasks/{run_id}/submissions")
def read_submissions(
    run_id: uuid.UUID, session: SessionDep, user: VerifiedUser, response: Response
) -> SubmissionState:
    response.headers["Cache-Control"] = "no-store"
    return state(session, run_id, user.id)


@router.post("/tasks/{run_id}/submissions", status_code=202)
def submit(
    run_id: uuid.UUID,
    body: Submit,
    session: SessionDep,
    user: VerifiedUser,
    response: Response,
) -> SubmissionState:
    response.headers["Cache-Control"] = "no-store"
    run = owned(session, run_id, user.id)
    lock_owner(session, user.id)
    session.refresh(run)
    submit_guard(session, run_id)
    if not run.candidate:
        raise HTTPException(409, "尚无已交付的完整案例")
    try:
        candidate = Candidate.model_validate(run.candidate)
    except ValueError:
        raise HTTPException(
            503, "案例快照无法校验；未提交或结算，请保留原记录"
        ) from None
    try:
        validate_answers(candidate, body.answers)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    answers = [a.model_dump() for a in body.answers]
    serialized = json.dumps(
        sorted(answers, key=lambda a: a["judgment_id"]),
        sort_keys=True,
        ensure_ascii=False,
    )
    digest = hashlib.sha256(
        (
            str(body.expected_config_version)
            + ("evaluation" if body.evaluate_after_submit else "")
            + serialized
        ).encode()
    ).hexdigest()
    existing = session.get(Submission, body.request_id)
    if existing:
        if (
            existing.run_id != run_id
            or existing.practice_help_id is not None
            or existing.input_hash != digest
        ):
            raise HTTPException(409, "提交身份已用于其他内容，请读取原记录；未覆盖原答")
        return state(session, run_id, user.id)
    duplicate = session.exec(
        select(Submission).where(
            Submission.run_id == run_id,
            Submission.input_hash == digest,
            col(Submission.practice_help_id).is_(None),
        )
    ).first()
    if duplicate:
        return state(session, run_id, user.id)
    evaluation = session.get(Evaluation, run.id)
    review = bool(evaluation and evaluation.frozen_sequence is not None)
    if evaluation and not review:
        raise HTTPException(
            409, "本轮评估已开始；许可中性补答请使用评分区域，原答不能覆盖"
        )
    if run.formal_submitted_at and not review:
        raise HTTPException(409, "本轮已完成，原答不可覆盖；复盘改答由后续功能提供")
    latest = session.exec(
        select(Submission)
        .where(Submission.run_id == run_id, col(Submission.practice_help_id).is_(None))
        .order_by(col(Submission.sequence).desc())
    ).first()
    if (latest.id if latest else None) != body.previous_submission_id:
        raise HTTPException(409, "已有另一份提交，请读取原记录后再决定补充；本次未覆盖")
    if latest and latest.status in {"checking", "stopping"}:
        raise HTTPException(409, "已有提交正在检查，请等待原提交结果")
    if not body.disclosure_accepted:
        raise HTTPException(
            422, "请确认将当前题面和本次作答发给已保存模型，重试可能计费"
        )
    config = session.get(ModelConfig, user.id, populate_existing=True)
    if not config or config.revoked or config.version != body.expected_config_version:
        raise HTTPException(409, "模型配置已变更或删除，请读取并确认本次目的地")
    if contains_secret(serialized) or decrypt(config).get_secret_value() in serialized:
        raise HTTPException(422, "作答疑似包含秘密，请脱敏后提交；检测不保证零漏报")
    submission = Submission(
        id=body.request_id,
        sequence=next_event(session, run.id),
        evaluate_after_submit=body.evaluate_after_submit,
        run_id=run.id,
        answers=answers,
        input_hash=digest,
        original_id=(latest.original_id or latest.id) if latest else None,
        kind="supplement"
        if review
        else "clarification"
        if latest and latest.neutral_clarification
        else "supplement"
        if latest
        else "original",
        config_version=config.version,
        destination=config.service_url,
        model_id=config.model_id,
    )
    session.add(submission)
    session.flush()
    if review:
        submission.status, submission.code, submission.message = (
            "completed",
            "review_saved",
            "复盘补充已保存，原答和冻结评分不变；未再次调用模型、评分或奖励",
        )
        session.add(submission)
    else:
        enqueue(session, submission)
    session.commit()
    return state(session, run_id, user.id)


@router.post("/tasks/{run_id}/submissions/{submission_id}/retry", status_code=202)
def retry_submission(
    run_id: uuid.UUID,
    submission_id: uuid.UUID,
    session: SessionDep,
    user: VerifiedUser,
    response: Response,
) -> SubmissionState:
    response.headers["Cache-Control"] = "no-store"
    owned(session, run_id, user.id)
    lock_owner(session, user.id)
    submission = session.get(Submission, submission_id, populate_existing=True)
    if not submission or submission.run_id != run_id:
        raise HTTPException(404, "提交不存在")
    if submission.status == "checking" or submission.status == "completed":
        return state(session, run_id, user.id)
    latest = session.exec(
        select(Submission.id)
        .where(
            Submission.run_id == run_id,
            Submission.practice_help_id == submission.practice_help_id,
        )
        .order_by(col(Submission.sequence).desc())
    ).first()
    if (
        latest != submission_id
        or submission.status not in {"failed", "stopped"}
        or submission.attempts >= 6
        or submission.code
        not in RETRYABLE | {"budget_exhausted", "stopped", "internal_failure"}
    ):
        raise HTTPException(
            409, "该提交不可重试或已耗尽六次预算；原答保留，未自动新增轮次"
        )
    config = session.get(ModelConfig, user.id)
    if not config or config.revoked or config.version != submission.config_version:
        raise HTTPException(409, "配置已变更，请读取并确认新目的地后主动补充")
    submission.status, submission.code, submission.message = (
        "checking",
        "queued",
        "已受理原提交重试；尚未完成或结算，重试可能计费",
    )
    submission.stop_requested = False
    submission.attempt_limit = min(6, submission.attempts + 3)
    enqueue(session, submission)
    session.commit()
    return state(session, run_id, user.id)


@router.post("/tasks/{run_id}/submissions/{submission_id}/stop")
def stop_submission(
    run_id: uuid.UUID,
    submission_id: uuid.UUID,
    session: SessionDep,
    user: VerifiedUser,
    response: Response,
) -> SubmissionState:
    response.headers["Cache-Control"] = "no-store"
    owned(session, run_id, user.id)
    submission = session.exec(
        select(Submission)
        .where(Submission.id == submission_id, Submission.run_id == run_id)
        .with_for_update()
    ).one_or_none()
    if not submission:
        raise HTTPException(404, "提交不存在")
    if submission.status not in {"checking", "stopping"}:
        return state(session, run_id, user.id)
    job_id = submission.queue_job_id
    submission.stop_requested, submission.status = True, "stopping"
    session.add(submission)
    session.commit()
    finish_submission_stop(submission.id, job_id)
    # The finisher commits in its own session; expose its current result (or a
    # newer retry), rather than this request's cached stopping intent.
    session.refresh(submission)
    return state(session, run_id, user.id)
