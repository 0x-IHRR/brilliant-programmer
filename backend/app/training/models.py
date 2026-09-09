import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Column, DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.training.submission_models import REWARD_RULE


class TrainingRun(SQLModel, table=True):
    __tablename__ = "training_run"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id", index=True)
    event_sequence: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    launch_mode: str = "practice"
    origin_id: uuid.UUID | None = Field(default=None, foreign_key="training_run.id")
    converted_sequence: int | None = Field(default=None, sa_column=Column(BigInteger))
    completion_rule_version: str = REWARD_RULE
    config_version: uuid.UUID
    destination: str
    model_id: str
    queue_job_id: int | None = Field(default=None, sa_column=Column(BigInteger))
    status: str = "queued"
    stop_requested: bool = False
    code: str = "queued"
    message: str = "等待后台生成"
    attempts: int = 0
    generation: int = 0
    generation_attempts: int = 0
    selection: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    target: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    sources: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    candidate: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    scenario_hash: str | None = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    # T08/#9 writes this only in the successful immutable formal-submission transaction.
    # Generation, drafts, failures and help never write it.
    formal_submitted_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )


class TrainingAttempt(SQLModel, table=True):
    __tablename__ = "training_attempt"
    __table_args__ = (UniqueConstraint("run_id", "number"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    run_id: uuid.UUID = Field(foreign_key="training_run.id", index=True)
    number: int
    generation: int
    # Written before external dispatch. A process death leaves unknown, not free.
    code: str = "unknown"
    prompt_tokens: int | None = Field(default=None, sa_column=Column(BigInteger))
    completion_tokens: int | None = Field(default=None, sa_column=Column(BigInteger))
    total_tokens: int | None = Field(default=None, sa_column=Column(BigInteger))
