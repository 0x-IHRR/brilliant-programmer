"""Immutable accepted inputs, bounded checks, and one award per existing round."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    Identity,
    Index,
    UniqueConstraint,
    text,
)
from sqlmodel import Field, SQLModel

REWARD_RULE = "completion-v1.0"
REWARD_POINTS = 10


class Submission(SQLModel, table=True):
    __tablename__ = "training_submission"
    __table_args__ = (
        UniqueConstraint("run_id", "input_hash"),
        Index(
            "one_original_per_run",
            "run_id",
            unique=True,
            postgresql_where=text("kind = 'original'"),
        ),
        Index(
            "one_neutral_clarification_per_run",
            "run_id",
            unique=True,
            postgresql_where=text("neutral_clarification"),
        ),
        Index(
            "one_clarification_answer_per_run",
            "run_id",
            unique=True,
            postgresql_where=text("kind = 'clarification'"),
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    sequence: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, Identity(), unique=True, nullable=False),
    )
    run_id: uuid.UUID = Field(foreign_key="training_run.id", index=True)
    original_id: uuid.UUID | None = Field(
        default=None, foreign_key="training_submission.id"
    )
    kind: str = "original"
    answers: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
    input_hash: str
    config_version: uuid.UUID
    destination: str
    model_id: str
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    stop_requested: bool = False
    status: str = "checking"
    code: str = "queued"
    message: str = "已受理原答，正在检查理由相关性；尚未完成或结算"
    relevance: list[dict[str, str]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    neutral_clarification: bool = False
    attempts: int = 0
    attempt_limit: int = 3
    queue_job_id: int | None = Field(default=None, sa_column=Column(BigInteger))


class SubmissionAttempt(SQLModel, table=True):
    __tablename__ = "submission_attempt"
    __table_args__ = (UniqueConstraint("submission_id", "number"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    submission_id: uuid.UUID = Field(foreign_key="training_submission.id", index=True)
    number: int
    code: str = "unknown"
    prompt_tokens: int | None = Field(default=None, sa_column=Column(BigInteger))
    completion_tokens: int | None = Field(default=None, sa_column=Column(BigInteger))
    total_tokens: int | None = Field(default=None, sa_column=Column(BigInteger))


class PracticeAward(SQLModel, table=True):
    __tablename__ = "practice_award"
    run_id: uuid.UUID = Field(primary_key=True, foreign_key="training_run.id")
    submission_id: uuid.UUID = Field(foreign_key="training_submission.id", unique=True)
    user_id: uuid.UUID = Field(foreign_key="user.id", index=True)
    points: int = REWARD_POINTS
    rule_version: str = REWARD_RULE
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
