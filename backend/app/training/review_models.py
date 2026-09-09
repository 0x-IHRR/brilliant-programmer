"""One accepted review per immutable evaluation, with per-call configuration."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    UniqueConstraint,
)
from sqlmodel import Field, SQLModel


class ScoreReview(SQLModel, table=True):
    __tablename__ = "score_review"
    run_id: uuid.UUID = Field(
        primary_key=True, foreign_key="training_evaluation.run_id"
    )
    request_id: uuid.UUID = Field(unique=True)
    snapshot: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    decision: str = "pending"
    opinion: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    status: str = "queued"
    code: str = "queued"
    message: str = "复核已受理；本次评分暂不参与能力计算，其他练习可继续"
    config_version: uuid.UUID
    destination: str
    model_id: str
    queue_job_id: int | None = Field(default=None, sa_column=Column(BigInteger))
    stop_requested: bool = False
    attempts: int = 0
    attempt_limit: int = 3
    accepted_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ReviewAttempt(SQLModel, table=True):
    __tablename__ = "review_attempt"
    __table_args__ = (UniqueConstraint("run_id", "number"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    run_id: uuid.UUID = Field(foreign_key="score_review.run_id", index=True)
    number: int
    config_version: uuid.UUID
    destination: str
    model_id: str
    code: str = "unknown"
    prompt_tokens: int | None = Field(default=None, sa_column=Column(BigInteger))
    completion_tokens: int | None = Field(default=None, sa_column=Column(BigInteger))
    total_tokens: int | None = Field(default=None, sa_column=Column(BigInteger))


class ReviewAward(SQLModel, table=True):
    __tablename__ = "review_award"
    __table_args__ = (CheckConstraint("points > 0"),)
    run_id: uuid.UUID = Field(primary_key=True, foreign_key="score_review.run_id")
    user_id: uuid.UUID = Field(foreign_key="user.id", index=True)
    points: int
    rule_version: str
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
