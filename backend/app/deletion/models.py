"""Content-free scopes and durable receipts; no source text or password storage."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column, DateTime
from sqlmodel import Field, SQLModel


class DeletionRequest(SQLModel, table=True):
    __tablename__ = "deletion_request"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id", index=True)
    kind: str
    target_id: uuid.UUID
    scope_digest: str
    authentication_digest: str
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    completed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )


class ErasedObject(SQLModel, table=True):
    __tablename__ = "erased_object"
    user_id: uuid.UUID = Field(primary_key=True, foreign_key="user.id")
    kind: str = Field(primary_key=True)
    object_id: uuid.UUID = Field(primary_key=True)
    request_id: uuid.UUID = Field(foreign_key="deletion_request.id")
    # Seen is an exposure fact, not a hash-based claim of semantic familiarity.
    seen: bool = False
    # Exact configuration/rule identity only; no source or answer text.
    binding_digest: str | None = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ErasedRow(SQLModel, table=True):
    __tablename__ = "erased_row"
    table_name: str = Field(primary_key=True)
    row_key: str = Field(primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id", index=True)
    request_id: uuid.UUID = Field(primary_key=True, foreign_key="deletion_request.id")
    # Only public field names and fixed empty values; never old content.
    cleared: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


class ArchivedObject(SQLModel, table=True):
    __tablename__ = "archived_object"
    user_id: uuid.UUID = Field(primary_key=True, foreign_key="user.id")
    kind: str = Field(primary_key=True)
    object_id: uuid.UUID = Field(primary_key=True)


class ErasedAttachment(SQLModel, table=True):
    __tablename__ = "erased_attachment"
    request_id: uuid.UUID = Field(primary_key=True, foreign_key="deletion_request.id")
    sha256: str = Field(primary_key=True)
