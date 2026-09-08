"""Owned evaluation lifecycle; hidden grading material never precedes freezing."""

import json
import uuid
from datetime import datetime

import procrastinate
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict
from sqlmodel import Session, col, select

from app.api.deps import SessionDep
from app.model_config.connection import Attempt
from app.model_config.models import ModelConfig
from app.model_config.service import decrypt, lock_owner
from app.training.evaluation_models import Evaluation, EvaluationAttempt
from app.training.evaluation_schema import (
    EvaluationInputs,
    GradingCandidate,
    InputSnapshot,
    evaluation_inputs,
)
from app.training.evaluation_service import create_evaluation, enqueue
from app.training.evaluation_worker import RETRYABLE, freeze
from app.training.events import next_event
from app.training.queue import DSN
from app.training.routes import VerifiedUser, owned
from app.training.schema import Candidate
from app.training.sources import contains_secret
from app.training.submission_models import Submission
from app.training.submission_schema import Answer, validate_answers

router = APIRouter(prefix="/training", tags=["evaluations"])


class EvaluationStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disclosure_accepted: bool
    expected_config_version: uuid.UUID


class Clarify(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answers: list[Answer] | None = None  # None explicitly ends clarification.


class EvaluationPublic(BaseModel):
    run_id: uuid.UUID
    status: str
    code: str
    message: str
    destination: str
    model_id: str
    frozen_sequence: int | None
    frozen_at: datetime | None
    inputs: EvaluationInputs
    result: GradingCandidate | None
    attempts: list[Attempt]
    can_retry: bool


def view(session: Session, item: Evaluation) -> EvaluationPublic:
    session.refresh(item)
    return EvaluationPublic(
        **item.model_dump(
            include={
                "run_id",
                "status",
                "code",
                "message",
                "destination",
                "model_id",
                "frozen_sequence",
                "frozen_at",
            }
        ),
        inputs=EvaluationInputs.model_validate_json(json.dumps(item.inputs)),
        result=GradingCandidate.model_validate(item.result)
        if item.result and item.frozen_sequence is not None
        else None,
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
                select(EvaluationAttempt)
                .where(EvaluationAttempt.run_id == item.run_id)
                .order_by(col(EvaluationAttempt.number))
            ).all()
        ],
        can_retry=item.status in {"failed", "stopped"}
        and item.attempts < 6
        and item.code
        in RETRYABLE | {"budget_exhausted", "internal_failure", "stopped"},
    )


@router.get("/tasks/{run_id}/evaluation")
def read_evaluation(
    run_id: uuid.UUID, session: SessionDep, user: VerifiedUser, response: Response
) -> EvaluationPublic | None:
    response.headers["Cache-Control"] = "no-store"
    owned(session, run_id, user.id)
    item = session.get(Evaluation, run_id)
    return view(session, item) if item else None


@router.post("/tasks/{run_id}/evaluation", status_code=202)
def start_evaluation(
    run_id: uuid.UUID,
    body: EvaluationStart,
    session: SessionDep,
    user: VerifiedUser,
    response: Response,
) -> EvaluationPublic:
    response.headers["Cache-Control"] = "no-store"
    run = owned(session, run_id, user.id)
    lock_owner(session, user.id)
    session.refresh(run)
    existing = session.get(Evaluation, run_id)
    if existing:
        return view(session, existing)
    submissions = list(
        session.exec(
            select(Submission)
            .where(Submission.run_id == run_id)
            .order_by(col(Submission.sequence))
        ).all()
    )
    if (
        not run.formal_submitted_at
        or not run.candidate
        or not submissions
        or any(s.status in {"checking", "stopping"} for s in submissions)
    ):
        raise HTTPException(409, "请先提交原答并等待当前相关性检查结束")
    if not body.disclosure_accepted:
        raise HTTPException(
            422,
            "请确认将当前冻结题、来源、原答和许可补答发送至已保存模型；重试可能计费",
        )
    config = session.get(ModelConfig, user.id, populate_existing=True)
    if not config or config.version != body.expected_config_version:
        raise HTTPException(409, "配置已变更，请重新核对评分目的地")
    inputs = evaluation_inputs(submissions)
    serialized = inputs.model_dump_json()
    if contains_secret(serialized) or decrypt(config).get_secret_value() in serialized:
        raise HTTPException(422, "原答疑似含秘密，未发送；检测不保证零漏报")
    item = create_evaluation(session, run, config)
    session.commit()
    return view(session, item)


@router.post("/tasks/{run_id}/evaluation/clarification", status_code=202)
def clarify_evaluation(
    run_id: uuid.UUID,
    body: Clarify,
    session: SessionDep,
    user: VerifiedUser,
    response: Response,
) -> EvaluationPublic:
    response.headers["Cache-Control"] = "no-store"
    owned(session, run_id, user.id)
    lock_owner(session, user.id)
    item = session.get(Evaluation, run_id, populate_existing=True)
    if not item:
        raise HTTPException(404, "评估不存在")
    if item.frozen_sequence is not None:
        return view(session, item)
    if item.status != "needs_clarification" or not item.clarification_requested:
        raise HTTPException(409, "当前没有许可的中性澄清")
    inputs = EvaluationInputs.model_validate_json(json.dumps(item.inputs))
    clarification = None
    if body.answers is not None:
        config = session.get(ModelConfig, user.id, populate_existing=True)
        if not config or config.version != item.config_version:
            raise HTTPException(409, "配置已变更；原答保留，未发送补答")
        try:
            validate_answers(Candidate.model_validate(item.case_snapshot), body.answers)
        except ValueError:
            raise HTTPException(422, "补答须覆盖原必答项并保留理由") from None
        serialized = json.dumps(
            [a.model_dump() for a in body.answers], ensure_ascii=False
        )
        if (
            contains_secret(serialized)
            or decrypt(config).get_secret_value() in serialized
        ):
            raise HTTPException(422, "补答疑似含秘密，未发送")
        clarification = InputSnapshot(
            id=uuid.uuid4(), sequence=next_event(session, run_id), answers=body.answers
        )
    item.inputs = inputs.model_copy(
        update={"clarification": clarification, "clarification_used": True}
    ).model_dump(mode="json")
    freeze(session, item)
    item.status, item.code, item.message = (
        "checking",
        "queued",
        "评估输入已冻结，正在核对；仍含糊只记尚未证明掌握",
    )
    item.attempt_limit = min(6, item.attempts + 3)
    if body.answers is None:
        item.status, item.code, item.message = (
            "completed",
            "evaluated",
            "已结束澄清并冻结原答；仍含糊的判断尚未证明掌握，不记录有据失败",
        )
        session.add(item)
    else:
        item.result = None
        enqueue(session, item)
    session.commit()
    return view(session, item)


@router.post("/tasks/{run_id}/evaluation/retry", status_code=202)
def retry_evaluation(
    run_id: uuid.UUID, session: SessionDep, user: VerifiedUser, response: Response
) -> EvaluationPublic:
    response.headers["Cache-Control"] = "no-store"
    owned(session, run_id, user.id)
    lock_owner(session, user.id)
    item = session.get(Evaluation, run_id, populate_existing=True)
    if not item:
        raise HTTPException(404, "评估不存在")
    if item.status in {"checking", "completed", "needs_clarification"}:
        return view(session, item)
    if not view(session, item).can_retry:
        raise HTTPException(409, "本轮不可继续或预算已耗尽；原答与奖励保留")
    config = session.get(ModelConfig, user.id, populate_existing=True)
    if not config or config.version != item.config_version:
        raise HTTPException(409, "配置已变更；旧评估不能继续调用")
    item.status, item.code, item.message = (
        "checking",
        "queued",
        "正在继续原评估，输入和预算不重置",
    )
    item.stop_requested = False
    item.attempt_limit = min(6, item.attempts + 3)
    enqueue(session, item)
    session.commit()
    return view(session, item)


@router.post("/tasks/{run_id}/evaluation/stop")
def stop_evaluation(
    run_id: uuid.UUID, session: SessionDep, user: VerifiedUser, response: Response
) -> EvaluationPublic:
    response.headers["Cache-Control"] = "no-store"
    owned(session, run_id, user.id)
    item = session.exec(
        select(Evaluation).where(Evaluation.run_id == run_id).with_for_update()
    ).one_or_none()
    if not item:
        raise HTTPException(404, "评估不存在")
    if item.status not in {"checking", "stopping"}:
        return view(session, item)
    stopped_job_id = item.queue_job_id
    item.stop_requested, item.status = True, "stopping"
    session.add(item)
    session.commit()
    with procrastinate.App(
        connector=procrastinate.SyncPsycopgConnector(conninfo=DSN)
    ).open() as app:
        if stopped_job_id is not None:
            app.job_manager.cancel_job_by_id(stopped_job_id, abort=True)
    lock_owner(session, user.id)
    session.refresh(item)
    if (
        item.status != "stopping"
        or not item.stop_requested
        or item.queue_job_id != stopped_job_id
    ):
        return view(session, item)
    item.status, item.code, item.message = (
        "stopped",
        "stopped",
        "评分已停止；原答与奖励保留，在途费用不保证撤回",
    )
    session.add(item)
    session.commit()
    return view(session, item)
