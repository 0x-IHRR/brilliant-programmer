"""One mutable saved editor per round, separate from submitted evidence."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, DateTime
from sqlmodel import Field, SQLModel


class TrainingDraft(SQLModel, table=True):
    __tablename__ = "training_draft"
    run_id: uuid.UUID = Field(primary_key=True, foreign_key="training_run.id")
    version: uuid.UUID
    request_id: uuid.UUID
    saved_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    progress: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
