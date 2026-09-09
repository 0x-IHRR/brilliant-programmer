"""JD provenance attached to the existing owner-scoped Topic lifecycle."""

import uuid
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class JDTopic(SQLModel, table=True):
    __tablename__ = "jd_topic"
    topic_id: uuid.UUID = Field(primary_key=True, foreign_key="topic.id")


class JDDocument(SQLModel, table=True):
    __tablename__ = "jd_document"
    # One immutable input per stable analysis request, including retries.
    id: uuid.UUID = Field(primary_key=True, foreign_key="topic_job.id")
    topic_id: uuid.UUID = Field(foreign_key="topic.id", index=True)
    text: str


class JDAnalysis(SQLModel, table=True):
    __tablename__ = "jd_analysis"
    document_id: uuid.UUID = Field(primary_key=True, foreign_key="jd_document.id")
    snapshot: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


class JDRoute(SQLModel, table=True):
    __tablename__ = "jd_route"
    version_id: uuid.UUID = Field(primary_key=True, foreign_key="topic_version.id")
    document_id: uuid.UUID = Field(foreign_key="jd_document.id", index=True)
    snapshot: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
