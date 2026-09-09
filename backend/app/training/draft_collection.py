"""Owned scope persistence. Caller holds User -> run through commit/submit."""

import json
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import JSON, Column
from sqlmodel import Field, Session, SQLModel, col, select

from app.training.draft_conflicts import (
    DraftVersions,
    new_versions,
    require_resolved,
    save_version,
)
from app.training.draft_models import TrainingDraft
from app.training.draft_schema import DraftSnapshot, JsonUUID, SaveDraft
from app.training.models import TrainingRun
from app.training.practice_models import PracticeDraft
from app.training.schema import Candidate, Strict
from app.training.submission_models import Submission


# ponytail: one JSON collection per scope under the run lock. If measured history
# size becomes a bottleneck, normalize storage; never trim unresolved versions.
class DraftCollection(SQLModel, table=True):
    __tablename__ = "draft_collection"
    scope_key: str = Field(primary_key=True)
    run_id: uuid.UUID = Field(foreign_key="training_run.id", index=True)
    help_id: uuid.UUID | None = Field(default=None, foreign_key="concept_help.id")
    data: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


class CollectionView(BaseModel):
    run_id: uuid.UUID
    help_id: uuid.UUID | None
    revision: uuid.UUID
    generation: uuid.UUID
    versions: list[DraftSnapshot]
    current: uuid.UUID | None
    unresolved: list[uuid.UUID]


class VersionReceipt(DraftSnapshot):
    revision: uuid.UUID
    generation: uuid.UUID


class VersionWrite(SaveDraft):
    observed_revision: JsonUUID
    generation: JsonUUID


class VersionChoice(Strict):
    observed_revision: JsonUUID
    version: JsonUUID


def key(run_id: uuid.UUID, help_id: uuid.UUID | None) -> str:
    return f"{run_id}:{help_id or 'original'}"


def lock_run(session: Session, run_id: uuid.UUID) -> TrainingRun:
    return session.exec(
        select(TrainingRun)
        .where(TrainingRun.id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()


def view(state: DraftVersions) -> CollectionView:
    return CollectionView.model_validate(asdict(state))


def load(
    session: Session, run_id: uuid.UUID, help_id: uuid.UUID | None = None
) -> DraftVersions:
    item = session.get(DraftCollection, key(run_id, help_id), populate_existing=True)
    if not item:
        state = new_versions(run_id, help_id)
        # Import existing current snapshot without changing its identity or payload.
        legacy = (
            session.get(PracticeDraft, help_id)
            if help_id
            else session.get(TrainingDraft, run_id)
        )
        if legacy:
            snapshot = DraftSnapshot.model_validate_json(
                legacy.model_dump_json(exclude={"help_id"})
            )
            state = DraftVersions(
                run_id,
                help_id,
                state.revision,
                state.generation,
                (snapshot,),
                snapshot.version,
            )
        store(session, state)
        return state
    data = CollectionView.model_validate_json(json.dumps(item.data))
    return DraftVersions(
        data.run_id,
        data.help_id,
        data.revision,
        data.generation,
        tuple(data.versions),
        data.current,
        tuple(data.unresolved),
    )


def store(session: Session, state: DraftVersions) -> None:
    session.merge(
        DraftCollection(
            scope_key=key(state.run_id, state.help_id),
            run_id=state.run_id,
            help_id=state.help_id,
            data=view(state).model_dump(mode="json"),
        )
    )
    current = next((s for s in state.versions if s.version == state.current), None)
    old = (
        session.get(PracticeDraft, state.help_id)
        if state.help_id
        else session.get(TrainingDraft, state.run_id)
    )
    if current:
        values = current.model_dump(exclude={"progress"}) | {
            "progress": current.progress.model_dump(mode="json")
        }
        session.merge(
            PracticeDraft(help_id=state.help_id, **values)
            if state.help_id
            else TrainingDraft(**values)
        )
    elif old:
        session.delete(old)


def save(
    session: Session,
    run: TrainingRun,
    candidate: Candidate,
    body: VersionWrite,
    help_id: uuid.UUID | None = None,
) -> VersionReceipt:
    state = load(session, run.id, help_id)
    latest = session.exec(
        select(Submission.id)
        .where(
            Submission.run_id == run.id,
            Submission.practice_help_id == help_id
            if help_id
            else col(Submission.practice_help_id).is_(None),
        )
        .order_by(col(Submission.sequence).desc())
    ).first()
    try:
        state, receipt = save_version(
            state,
            candidate=candidate,
            request=body,
            observed_revision=body.observed_revision,
            generation=body.generation,
            latest_submission_id=latest,
            saved_at=datetime.now(UTC),
        )
    except ValueError:
        raise HTTPException(422, "草稿与题目不匹配；输入保留") from None
    store(session, state)
    session.commit()
    if state.unresolved or state.current != receipt.version:
        raise HTTPException(
            409,
            "输入版本已保存，当前存在冲突或另一个已选版本；请读取全部版本后明确选择。",
        )
    return VersionReceipt(
        **receipt.model_dump(), revision=state.revision, generation=state.generation
    )


def submit_guard(
    session: Session, run_id: uuid.UUID, help_id: uuid.UUID | None = None
) -> None:
    lock_run(session, run_id)
    require_resolved(load(session, run_id, help_id))
