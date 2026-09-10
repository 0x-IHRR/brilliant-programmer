"""No User foreign key: deletion intent must not wait for a model's User lock."""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel


class AccountErasure(SQLModel, table=True):
    __tablename__ = "account_erasure"
    user_id: uuid.UUID = Field(primary_key=True)
    request_id: uuid.UUID = Field(default_factory=uuid.uuid4, unique=True)
    authentication_digest: str
    receipt_hash: str
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    accepted_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    completed_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))


class JournalState(SQLModel, table=True):
    __tablename__ = "account_journal_state"
    id: int = Field(default=1, primary_key=True)
    identity: str
    sequence: int = 0


class ErasurePermit(SQLModel, table=True):
    __tablename__ = "account_erasure_permit"
    user_id: uuid.UUID = Field(primary_key=True)
    table_name: str = Field(primary_key=True)
    row_key: str = Field(primary_key=True)
    request_id: uuid.UUID
