"""Owner-scoped route pointers and immutable historical candidate snapshots."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Column, DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel


class Topic(SQLModel, table=True):
    __tablename__ = "topic"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id", index=True)
    current_id: uuid.UUID | None = None
    active_id: uuid.UUID | None = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class TopicVersion(SQLModel, table=True):
    __tablename__ = "topic_version"
    id: uuid.UUID = Field(primary_key=True)
    topic_id: uuid.UUID = Field(foreign_key="topic.id", index=True)
    snapshot: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


class TopicJob(SQLModel, table=True):
    __tablename__ = "topic_job"
    id: uuid.UUID = Field(primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id", index=True)
    topic_id: uuid.UUID = Field(foreign_key="topic.id", index=True)
    expected_version: uuid.UUID | None = None
    input_text: str
    expand: bool = False
    config_version: uuid.UUID
    destination: str
    model_id: str
    queue_job_id: int | None = Field(default=None, sa_column=Column(BigInteger))
    status: str = "queued"
    code: str = "queued"
    message: str = "等待分析主题；尚未生成题目"
    stop_requested: bool = False
    attempts: int = 0
    attempt_limit: int = 3
    stage: str = "analyze"
    candidate: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    result_id: uuid.UUID | None = None


class TopicAttempt(SQLModel, table=True):
    __tablename__ = "topic_attempt"
    __table_args__ = (UniqueConstraint("run_id", "number"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    run_id: uuid.UUID = Field(foreign_key="topic_job.id", index=True)
    number: int
    stage: str
    code: str = "unknown"
    prompt_tokens: int | None = Field(default=None, sa_column=Column(BigInteger))
    completion_tokens: int | None = Field(default=None, sa_column=Column(BigInteger))
    total_tokens: int | None = Field(default=None, sa_column=Column(BigInteger))


class TopicCase(SQLModel, table=True):
    __tablename__ = "topic_case"
    run_id: uuid.UUID = Field(primary_key=True, foreign_key="training_run.id")
    candidate: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
