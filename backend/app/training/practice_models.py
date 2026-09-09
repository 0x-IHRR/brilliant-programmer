"""A separate editor scope for a delivered demonstration's small exercise."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, DateTime
from sqlmodel import Field, SQLModel


class PracticeDraft(SQLModel, table=True):
    __tablename__ = "practice_draft"
    help_id: uuid.UUID = Field(primary_key=True, foreign_key="concept_help.id")
    run_id: uuid.UUID = Field(foreign_key="training_run.id")
    version: uuid.UUID
    request_id: uuid.UUID
    saved_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    progress: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
