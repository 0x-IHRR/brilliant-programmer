"""Allocate round-local order under the same row lock as the caller's event."""

import uuid

from sqlmodel import Session, select

from app.training.models import TrainingRun


def next_event(session: Session, run_id: uuid.UUID) -> int:
    run = session.exec(
        select(TrainingRun)
        .where(TrainingRun.id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    run.event_sequence += 1
    session.add(run)
    session.flush()
    return run.event_sequence
