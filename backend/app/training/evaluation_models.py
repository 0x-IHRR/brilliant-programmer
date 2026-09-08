"""One immutable evaluation boundary per round; no ability or reward writes."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Column, DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.training.evaluation_schema import EVALUATION_RULE


class Evaluation(SQLModel, table=True):
    __tablename__ = "training_evaluation"
    run_id: uuid.UUID = Field(primary_key=True, foreign_key="training_run.id")
    inputs: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    case_snapshot: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    sources: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
    rule_version: str = EVALUATION_RULE
    config_version: uuid.UUID
    destination: str
    model_id: str
    status: str = "checking"
    code: str = "queued"
    message: str = "正在逐项核对原答；尚未形成掌握结论"
    clarification_requested: bool = False
    frozen_sequence: int | None = None
    frozen_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    result: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    attempts: int = 0
    attempt_limit: int = 3
    stop_requested: bool = False
    queue_job_id: int | None = Field(default=None, sa_column=Column(BigInteger))


class EvaluationAttempt(SQLModel, table=True):
    __tablename__ = "evaluation_attempt"
    __table_args__ = (UniqueConstraint("run_id", "number"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    run_id: uuid.UUID = Field(foreign_key="training_evaluation.run_id", index=True)
    number: int
    code: str = "unknown"
    prompt_tokens: int | None = Field(default=None, sa_column=Column(BigInteger))
    completion_tokens: int | None = Field(default=None, sa_column=Column(BigInteger))
    total_tokens: int | None = Field(default=None, sa_column=Column(BigInteger))
