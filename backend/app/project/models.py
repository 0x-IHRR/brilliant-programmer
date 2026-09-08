import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Column, DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel


class ProjectRun(SQLModel, table=True):
    __tablename__ = "project_run"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id", index=True)
    url: str
    reanalyze: bool = False
    config_version: uuid.UUID
    destination: str
    model_id: str
    queue_job_id: int | None = Field(default=None, sa_column=Column(BigInteger))
    reused_from_id: uuid.UUID | None = Field(default=None, foreign_key="project_run.id")
    repository_key: str | None = Field(default=None, index=True)
    commit: str | None = Field(default=None, index=True)
    status: str = "queued"
    code: str = "queued"
    message: str = "等待固定 GitHub 版本"
    stop_requested: bool = False
    acquisition_done: bool = False
    attempts: int = 0
    generation: int = 0
    generation_attempts: int = 0
    snapshot: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    project_map: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ProjectAttempt(SQLModel, table=True):
    __tablename__ = "project_attempt"
    __table_args__ = (UniqueConstraint("run_id", "number"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    run_id: uuid.UUID = Field(foreign_key="project_run.id", index=True)
    number: int
    generation: int
    code: str = "unknown"
    prompt_tokens: int | None = Field(default=None, sa_column=Column(BigInteger))
    completion_tokens: int | None = Field(default=None, sa_column=Column(BigInteger))
    total_tokens: int | None = Field(default=None, sa_column=Column(BigInteger))
