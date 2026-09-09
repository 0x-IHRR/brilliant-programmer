"""Append-only evaluation evidence and per-round admission facts."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column, DateTime, LargeBinary, UniqueConstraint
from sqlmodel import Field, SQLModel


class QualityReport(SQLModel, table=True):
    __tablename__ = "quality_report"
    __table_args__ = (UniqueConstraint("user_id", "sequence"),)
    id: uuid.UUID = Field(primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id", index=True)
    sequence: int
    artifact_sha256: str = Field(unique=True)
    report: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    outcome: str
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class QualityDisposition(SQLModel, table=True):
    __tablename__ = "quality_disposition"
    run_id: uuid.UUID = Field(primary_key=True, foreign_key="training_run.id")
    phase: str = Field(primary_key=True)
    report_id: uuid.UUID | None = Field(default=None, foreign_key="quality_report.id")
    status: str
    binding: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class QualityEvidence(SQLModel, table=True):
    __tablename__ = "quality_evidence"
    sha256: str = Field(primary_key=True)
    content: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
