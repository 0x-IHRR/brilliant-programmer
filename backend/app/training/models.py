import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column, DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel


class TrainingRun(SQLModel, table=True):
    __tablename__ = "training_run"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id", index=True)
    config_version: uuid.UUID
    destination: str
    model_id: str
    queue_job_id: int | None = None
    status: str = "queued"
    stop_requested: bool = False
    code: str = "queued"
    message: str = "等待后台生成"
    attempts: int = 0
    generation: int = 0
    generation_attempts: int = 0
    target: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    sources: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    candidate: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    scenario_hash: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), sa_column=Column(DateTime(timezone=True)))
    # T08/#9 writes this only in the successful immutable formal-submission transaction.
    # Generation, drafts, failures and help never write it.
    formal_submitted_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))


class TrainingAttempt(SQLModel, table=True):
    __tablename__ = "training_attempt"
    __table_args__ = (UniqueConstraint("run_id", "number"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    run_id: uuid.UUID = Field(foreign_key="training_run.id", index=True)
    number: int
    generation: int
    # Written before external dispatch. A process death leaves unknown, not free.
    code: str = "unknown"
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
