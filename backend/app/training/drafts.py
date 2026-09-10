"""Owned optimistic draft saves; no queue, model, submission or reward mutation."""

import uuid

from fastapi import APIRouter, HTTPException, Response
from sqlmodel import select

from app.api.deps import SessionDep
from app.model_config.service import lock_owner
from app.training import draft_collection as collections
from app.training.draft_conflicts import choose_version, delete_current
from app.training.draft_models import TrainingDraft
from app.training.draft_schema import DraftSnapshot
from app.training.models import TrainingRun
from app.training.routes import VerifiedUser, owned
from app.training.schema import Candidate

router = APIRouter(prefix="/training", tags=["drafts"])


def snapshot(item: TrainingDraft) -> DraftSnapshot:
    return DraftSnapshot.model_validate_json(item.model_dump_json())


@router.get("/tasks/{run_id}/draft")
def read_draft(
    run_id: uuid.UUID, session: SessionDep, user: VerifiedUser, response: Response
) -> DraftSnapshot | None:
    response.headers["Cache-Control"] = "no-store"
    from app.training.projection import read_snapshot

    with read_snapshot(user.id) as session:
        owned(session, run_id, user.id)
        item = session.get(TrainingDraft, run_id)
        return snapshot(item) if item else None


@router.put("/tasks/{run_id}/draft")
def save_draft(
    run_id: uuid.UUID,
    body: collections.VersionWrite,
    session: SessionDep,
    user: VerifiedUser,
    response: Response,
) -> collections.VersionReceipt:
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
    return collections.save(session, run, Candidate.model_validate(run.candidate), body)


@router.get("/tasks/{run_id}/draft/versions")
def read_versions(
    run_id: uuid.UUID, session: SessionDep, user: VerifiedUser, response: Response
) -> collections.CollectionView:
    owned(session, run_id, user.id)
    lock_owner(session, user.id)
    collections.lock_run(session, run_id)
    result = collections.load(session, run_id)
    session.commit()
    response.headers["Cache-Control"] = "no-store"
    return collections.view(result)


@router.post("/tasks/{run_id}/draft/choose")
def choose_draft(
    run_id: uuid.UUID,
    body: collections.VersionChoice,
    session: SessionDep,
    user: VerifiedUser,
    response: Response,
) -> collections.CollectionView:
    owned(session, run_id, user.id)
    lock_owner(session, user.id)
    collections.lock_run(session, run_id)
    result = choose_version(collections.load(session, run_id), **body.model_dump())
    collections.store(session, result)
    session.commit()
    response.headers["Cache-Control"] = "no-store"
    return collections.view(result)


@router.delete("/tasks/{run_id}/draft")
def delete_draft(
    run_id: uuid.UUID,
    body: collections.VersionChoice,
    session: SessionDep,
    user: VerifiedUser,
    response: Response,
) -> collections.CollectionView:
    owned(session, run_id, user.id)
    lock_owner(session, user.id)
    collections.lock_run(session, run_id)
    result = delete_current(collections.load(session, run_id), **body.model_dump())
    collections.store(session, result)
    session.commit()
    response.headers["Cache-Control"] = "no-store"
    return collections.view(result)
