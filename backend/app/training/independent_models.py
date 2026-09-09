"""Private novelty work and append-only qualification observations."""

import uuid
from typing import Any

from sqlalchemy import JSON, BigInteger, Column, UniqueConstraint
from sqlmodel import Field, SQLModel


class IndependentWork(SQLModel, table=True):
    __tablename__ = "independent_work"
    run_id: uuid.UUID = Field(primary_key=True, foreign_key="training_run.id")
    candidate: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    history: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    novelty: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    # Versioned complete snapshot and exact request plan. Legacy history/novelty
    # remain untouched; adapters select format by the presence of this snapshot.
    history_snapshot: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON)
    )
    comparison_plan: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    comparison_results: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )


class IndependentObservation(SQLModel, table=True):
    __tablename__ = "independent_observation"
    __table_args__ = (UniqueConstraint("run_id", "sequence"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    run_id: uuid.UUID = Field(foreign_key="training_run.id", index=True)
    sequence: int = Field(sa_column=Column(BigInteger, nullable=False))
    frozen_sequence: int = Field(sa_column=Column(BigInteger, nullable=False))
    original_id: uuid.UUID
    case_digest: str
    target: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    outcome: str
    rule_version: str = "independent-v1"
    semantic_reliability: str = "unverified"


class HelpConfirmation(SQLModel, table=True):
    __tablename__ = "help_confirmation"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    run_id: uuid.UUID = Field(foreign_key="training_run.id", index=True)
    help_id: uuid.UUID = Field(foreign_key="concept_help.id")
    sequence: int = Field(sa_column=Column(BigInteger, nullable=False))
    content_hash: str
    direction: str
