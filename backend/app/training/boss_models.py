"""Immutable accepted stage and promotion facts, linked to the existing round."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Column, DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel


class BossAttempt(SQLModel, table=True):
    __tablename__ = "boss_attempt"
    run_id: uuid.UUID = Field(primary_key=True, foreign_key="training_run.id")
    stage: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    launch_points: int
    launch_level: str
    promotion_blocked: bool = False
    revalidation_event_id: uuid.UUID | None = Field(
        default=None, foreign_key="boss_revalidation.id"
    )
    revalidation_of: uuid.UUID | None = Field(
        default=None, foreign_key="boss_promotion.id"
    )


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


class BossRevalidation(SQLModel, table=True):
    __tablename__ = "boss_revalidation"
    __table_args__ = (
        UniqueConstraint("promotion_id", "sequence"),
        CheckConstraint(
            "sequence > 0 AND ((kind = 'required' AND review_run_id IS NOT NULL AND resolved_run_id IS NULL) OR (kind = 'resolved' AND review_run_id IS NULL AND resolved_run_id IS NOT NULL))",
            name="revalidation_event_shape",
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    promotion_id: uuid.UUID = Field(foreign_key="boss_promotion.id")
    sequence: int
    kind: str
    review_run_id: uuid.UUID | None = Field(
        default=None, unique=True, foreign_key="score_review.run_id"
    )
    resolved_run_id: uuid.UUID | None = Field(
        default=None, unique=True, foreign_key="boss_attempt.run_id"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class BossDisposition(SQLModel, table=True):
    __tablename__ = "boss_disposition"
    run_id: uuid.UUID = Field(primary_key=True, foreign_key="boss_attempt.run_id")
    outcome: str
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
