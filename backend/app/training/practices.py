"""Owned same-round exercises, only after a recorded demonstration rendering."""

import hashlib
import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from sqlmodel import Session, col, select

from app.api.deps import SessionDep
from app.model_config.models import ModelConfig
from app.model_config.output import check_output
from app.model_config.service import decrypt, lock_owner
from app.training.concept_models import HelpDelivery
from app.training.concepts import help_owned
from app.training.draft_save import prepare_save
from app.training.draft_schema import DraftSnapshot, SaveDraft
from app.training.events import next_event
from app.training.guided import PracticeCase, exercise_candidate, practice_case
from app.training.models import TrainingRun
from app.training.practice_models import PracticeDraft
from app.training.routes import VerifiedUser, owned
from app.training.schema import Candidate, Source
from app.training.submission_models import Submission
from app.training.submission_schema import SubmissionState, Submit, validate_answers
from app.training.submissions import enqueue, retry_submission, state, stop_submission

router = APIRouter(
    prefix="/training/tasks/{run_id}/help/{help_id}/practice", tags=["practice"]
)


class PracticeState(BaseModel):
    help_id: uuid.UUID
    exercise: PracticeCase
    records: SubmissionState
    completed: bool


def exercise_for(
    session: Session, run_id: uuid.UUID, help_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[TrainingRun, Candidate]:
    help = help_owned(session, run_id, help_id, user_id)
    receipt = session.exec(
        select(HelpDelivery.id).where(
            HelpDelivery.help_id == help_id, HelpDelivery.status == "delivered"
        )
    ).first()
    if help.kind != "demonstration" or help.status != "ready" or not receipt:
        raise HTTPException(409, "请先主动查看完整示范并保存实际渲染回执，再自行跟练")
    run = owned(session, run_id, user_id)
    candidate = Candidate.model_validate(run.candidate)
    return run, exercise_candidate(candidate, candidate.judgments[0].id)


def view(
    session: Session, run_id: uuid.UUID, help_id: uuid.UUID, user_id: uuid.UUID
) -> PracticeState:
    run, exercise = exercise_for(session, run_id, help_id, user_id)
    records = state(session, run_id, user_id, help_id)
    return PracticeState(
        help_id=help_id,
        exercise=practice_case(
            Candidate.model_validate(run.candidate),
            [Source.model_validate(s) for s in run.sources],
            exercise.judgments[0].id,
            "",
        ),
        records=records,
        completed=any(item.status == "completed" for item in records.submissions),
    )


@router.get("")
def read_practice(
    run_id: uuid.UUID,
    help_id: uuid.UUID,
    session: SessionDep,
    user: VerifiedUser,
    response: Response,
) -> PracticeState:
    response.headers["Cache-Control"] = "no-store"
    return view(session, run_id, help_id, user.id)


@router.post("", status_code=202)
def submit_practice(
    run_id: uuid.UUID,
    help_id: uuid.UUID,
    body: Submit,
    session: SessionDep,
    user: VerifiedUser,
    response: Response,
) -> PracticeState:
    response.headers["Cache-Control"] = "no-store"
    run, candidate = exercise_for(session, run_id, help_id, user.id)
    lock_owner(session, user.id)
    if body.evaluate_after_submit:
        raise HTTPException(422, "跟练不作为原题独立评估")
    try:
        validate_answers(candidate, body.answers)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    answers = [a.model_dump() for a in body.answers]
    serialized = json.dumps(answers, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(
        (str(help_id) + str(body.expected_config_version) + serialized).encode()
    ).hexdigest()
    existing = session.get(Submission, body.request_id)
    if existing:
        if (
            existing.run_id != run_id
            or existing.practice_help_id != help_id
            or existing.input_hash != digest
        ):
            raise HTTPException(409, "提交标识已用于其他输入；原记录未覆盖")
        return view(session, run_id, help_id, user.id)
    prior = list(
        session.exec(
            select(Submission)
            .where(Submission.run_id == run_id, Submission.practice_help_id == help_id)
            .order_by(col(Submission.sequence))
        ).all()
    )
    if any(s.input_hash == digest for s in prior):
        return view(session, run_id, help_id, user.id)
    latest = prior[-1] if prior else None
    if body.previous_submission_id != (latest.id if latest else None):
        raise HTTPException(409, "跟练已有另一份提交，请读取记录；本机输入保留")
    if latest and latest.status in {"checking", "stopping"}:
        raise HTTPException(409, "请等待当前跟练检查或停止")
    completed = any(s.status == "completed" for s in prior)
    config = session.get(ModelConfig, user.id, populate_existing=True)
    if not completed and (
        not body.disclosure_accepted
        or not config
        or config.version != body.expected_config_version
    ):
        raise HTTPException(409, "请核对已保存模型目的地并允许检查当前跟练作答")
    try:
        check_output(serialized, decrypt(config).get_secret_value() if config else "")
    except ValueError:
        raise HTTPException(422, "作答疑似含秘密，请脱敏") from None
    if completed:
        assert latest
        destination, model_id = latest.destination, latest.model_id
    else:
        assert config
        destination, model_id = config.service_url, config.model_id
    item = Submission(
        id=body.request_id,
        run_id=run_id,
        kind="practice",
        practice_help_id=help_id,
        practice_judgment_id=candidate.judgments[0].id,
        original_id=prior[0].id if prior else None,
        sequence=next_event(session, run_id),
        answers=answers,
        input_hash=digest,
        config_version=latest.config_version
        if completed and latest
        else body.expected_config_version,
        destination=destination,
        model_id=model_id,
    )
    if completed:
        item.status, item.code, item.message = (
            "completed",
            "review_saved",
            "跟练复盘已保存；未重评、未新增奖励，原题记录保留。",
        )
    else:
        item.message = "跟练已受理，正在检查理由相关性；尚未确认完成。"
    session.add(item)
    session.flush()
    if not completed:
        enqueue(session, item)
    session.commit()
    return view(session, run_id, help_id, user.id)


def submission_owned(
    session: Session,
    run_id: uuid.UUID,
    help_id: uuid.UUID,
    submission_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    exercise_for(session, run_id, help_id, user_id)
    item = session.get(Submission, submission_id)
    if not item or item.run_id != run_id or item.practice_help_id != help_id:
        raise HTTPException(404, "跟练提交不存在")


@router.post("/{submission_id}/retry", status_code=202)
def retry_practice(
    run_id: uuid.UUID,
    help_id: uuid.UUID,
    submission_id: uuid.UUID,
    session: SessionDep,
    user: VerifiedUser,
    response: Response,
) -> PracticeState:
    submission_owned(session, run_id, help_id, submission_id, user.id)
    retry_submission(run_id, submission_id, session, user, response)
    return view(session, run_id, help_id, user.id)


@router.post("/{submission_id}/stop")
def stop_practice(
    run_id: uuid.UUID,
    help_id: uuid.UUID,
    submission_id: uuid.UUID,
    session: SessionDep,
    user: VerifiedUser,
    response: Response,
) -> PracticeState:
    submission_owned(session, run_id, help_id, submission_id, user.id)
    stop_submission(run_id, submission_id, session, user, response)
    return view(session, run_id, help_id, user.id)


@router.get("/draft")
def read_practice_draft(
    run_id: uuid.UUID,
    help_id: uuid.UUID,
    session: SessionDep,
    user: VerifiedUser,
    response: Response,
) -> DraftSnapshot | None:
    response.headers["Cache-Control"] = "no-store"
    exercise_for(session, run_id, help_id, user.id)
    item = session.get(PracticeDraft, help_id)
    return (
        DraftSnapshot.model_validate_json(item.model_dump_json(exclude={"help_id"}))
        if item
        else None
    )


@router.put("/draft")
def save_practice_draft(
    run_id: uuid.UUID,
    help_id: uuid.UUID,
    body: SaveDraft,
    session: SessionDep,
    user: VerifiedUser,
    response: Response,
) -> DraftSnapshot:
    response.headers["Cache-Control"] = "no-store"
    _, candidate = exercise_for(session, run_id, help_id, user.id)
    lock_owner(session, user.id)
    session.exec(
        select(TrainingRun).where(TrainingRun.id == run_id).with_for_update()
    ).one()
    item = session.get(PracticeDraft, help_id, populate_existing=True)
    current = (
        DraftSnapshot.model_validate_json(item.model_dump_json(exclude={"help_id"}))
        if item
        else None
    )
    latest = session.exec(
        select(Submission.id)
        .where(Submission.practice_help_id == help_id)
        .order_by(col(Submission.sequence).desc())
    ).first()
    try:
        result = prepare_save(
            run_id=run_id,
            candidate=candidate,
            current=current,
            request=body,
            latest_submission_id=latest,
            saved_at=datetime.now(UTC),
        )
    except ValueError:
        raise HTTPException(422, "跟练草稿格式不符；输入保留") from None
    if not item:
        item = PracticeDraft(
            help_id=help_id,
            **result.model_dump(exclude={"progress"}),
            progress=result.progress.model_dump(mode="json"),
        )
    elif item.version != result.version:
        item.version, item.request_id, item.saved_at = (
            result.version,
            result.request_id,
            result.saved_at,
        )
        item.progress = result.progress.model_dump(mode="json")
    session.add(item)
    session.commit()
    return result
