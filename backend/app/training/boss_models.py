"""Immutable accepted stage and promotion facts, linked to the existing round."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column, DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel


class BossAttempt(SQLModel, table=True):
    __tablename__ = "boss_attempt"
    run_id: uuid.UUID = Field(primary_key=True, foreign_key="training_run.id")
    stage: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    launch_points: int
    launch_level: str


class BossPromotion(SQLModel, table=True):
    __tablename__ = "boss_promotion"
    __table_args__ = (UniqueConstraint("user_id", "from_level"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id")
    run_id: uuid.UUID = Field(unique=True, foreign_key="boss_attempt.run_id")
    original_id: uuid.UUID = Field(foreign_key="training_submission.id")
    frozen_sequence: int
    stage_version: str
    from_level: str
    to_level: str
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
