"""Private generated help and append-only, round-ordered delivery observations."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Column, DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel


class ConceptHelp(SQLModel, table=True):
    __tablename__ = "concept_help"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    run_id: uuid.UUID = Field(foreign_key="training_run.id", index=True)
    kind: str = "concept"
    parent_id: uuid.UUID | None = Field(default=None, foreign_key="concept_help.id")
    created_sequence: int = Field(sa_column=Column(BigInteger, nullable=False))
    generated_sequence: int | None = Field(default=None, sa_column=Column(BigInteger))
    checked_sequence: int | None = Field(default=None, sa_column=Column(BigInteger))
    request: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    config_version: uuid.UUID
    destination: str
    model_id: str
    status: str = "checking"
    stage: str = "generate"
    code: str = "queued"
    message: str = "正在准备概念说明，尚未交付"
    content: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON(none_as_null=True))
    )
    inspection: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON(none_as_null=True))
    )
    direction: str | None = None
    stop_requested: bool = False
    attempts: int = 0
    stage_attempts: int = 0
    attempt_limit: int = 3
    queue_job_id: int | None = Field(default=None, sa_column=Column(BigInteger))


class ConceptAttempt(SQLModel, table=True):
    __tablename__ = "concept_attempt"
    __table_args__ = (UniqueConstraint("help_id", "number"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    help_id: uuid.UUID = Field(foreign_key="concept_help.id", index=True)
    number: int
    stage: str
    code: str = "unknown"
    prompt_tokens: int | None = Field(default=None, sa_column=Column(BigInteger))
    completion_tokens: int | None = Field(default=None, sa_column=Column(BigInteger))
    total_tokens: int | None = Field(default=None, sa_column=Column(BigInteger))


class HelpDelivery(SQLModel, table=True):
    __tablename__ = "help_delivery"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence"),
        UniqueConstraint("attempt_id"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    help_id: uuid.UUID = Field(foreign_key="concept_help.id", index=True)
    run_id: uuid.UUID = Field(foreign_key="training_run.id", index=True)
    sequence: int = Field(sa_column=Column(BigInteger, nullable=False))
    # A later rendering receipt points back to the original publication attempt.
    # It cannot move a possibly pre-freeze exposure behind the freeze boundary.
    exposure_sequence: int = Field(sa_column=Column(BigInteger, nullable=False))
    attempt_id: uuid.UUID | None = Field(default=None, foreign_key="help_delivery.id")
    status: str
    delivered_text: str = ""
    direction: str | None = None
    content_hash: str
    receipt_hash: str | None = None
    evidence: str = "server_publication_attempt"
    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
