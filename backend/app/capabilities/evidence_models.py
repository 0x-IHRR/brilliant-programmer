"""Immutable per-owner ordering of original answers, separate from round events."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel


class OriginalOrder(SQLModel, table=True):
    __tablename__ = "capability_original_order"
    __table_args__ = (UniqueConstraint("user_id", "position"),)
    original_id: uuid.UUID = Field(
        primary_key=True, foreign_key="training_submission.id"
    )
    user_id: uuid.UUID = Field(foreign_key="user.id", index=True)
    position: int = Field(sa_column=Column(BigInteger, nullable=False))
    submitted_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    source: str = "user_locked"
