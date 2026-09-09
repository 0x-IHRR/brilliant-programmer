"""Owned optimistic draft saves; no queue, model, submission or reward mutation."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Response
from sqlmodel import col, select

from app.api.deps import SessionDep
from app.model_config.service import lock_owner
from app.training.draft_models import TrainingDraft
from app.training.draft_save import prepare_save
from app.training.draft_schema import DraftSnapshot, SaveDraft
from app.training.models import TrainingRun
from app.training.routes import VerifiedUser, owned
from app.training.schema import Candidate
from app.training.submission_models import Submission

router = APIRouter(prefix="/training", tags=["drafts"])


def snapshot(item: TrainingDraft) -> DraftSnapshot:
    return DraftSnapshot.model_validate_json(item.model_dump_json())


@router.get("/tasks/{run_id}/draft")
def read_draft(
    run_id: uuid.UUID, session: SessionDep, user: VerifiedUser, response: Response
) -> DraftSnapshot | None:
    response.headers["Cache-Control"] = "no-store"
    owned(session, run_id, user.id)
    item = session.get(TrainingDraft, run_id)
    return snapshot(item) if item else None


@router.put("/tasks/{run_id}/draft")
def save_draft(
    run_id: uuid.UUID,
    body: SaveDraft,
    session: SessionDep,
    user: VerifiedUser,
    response: Response,
) -> DraftSnapshot:
    response.headers["Cache-Control"] = "no-store"
    owned(session, run_id, user.id)
    lock_owner(session, user.id)
    run = session.exec(
        select(TrainingRun)
        .where(TrainingRun.id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    if run.status != "completed" or not run.candidate:
        raise HTTPException(409, "请先取得当前完整案例；当前输入保留")
    current = session.get(TrainingDraft, run_id, populate_existing=True)
    latest = session.exec(
        select(Submission.id)
        .where(Submission.run_id == run_id, col(Submission.practice_help_id).is_(None))
        .order_by(col(Submission.sequence).desc())
    ).first()
    try:
        result = prepare_save(
            run_id=run_id,
            candidate=Candidate.model_validate(run.candidate),
            current=snapshot(current) if current else None,
            request=body,
            latest_submission_id=latest,
            saved_at=datetime.now(UTC),
        )
    except ValueError:
        raise HTTPException(
            422, "草稿与当前题目不匹配；当前输入保留，请核对判断和选项"
        ) from None
    if current is None:
        current = TrainingDraft(
            **result.model_dump(exclude={"progress"}),
            progress=result.progress.model_dump(mode="json"),
        )
    elif result.version != current.version:
        current.version, current.request_id, current.saved_at = (
            result.version,
            result.request_id,
            result.saved_at,
        )
        current.progress = result.progress.model_dump(mode="json")
    session.add(current)
    session.commit()
    return result
