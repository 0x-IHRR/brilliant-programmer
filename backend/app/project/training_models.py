"""Immutable project provenance attached to the existing Topic lifecycle."""

import uuid
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class ProjectTopic(SQLModel, table=True):
    __tablename__ = "project_topic"
    topic_id: uuid.UUID = Field(primary_key=True, foreign_key="topic.id")
    project_run_id: uuid.UUID = Field(foreign_key="project_run.id", index=True)


class ProjectInput(SQLModel, table=True):
    __tablename__ = "project_training_input"
    id: uuid.UUID = Field(primary_key=True, foreign_key="topic_job.id")
    topic_id: uuid.UUID = Field(foreign_key="topic.id", index=True)
    project_run_id: uuid.UUID = Field(foreign_key="project_run.id")
    previous_version_id: uuid.UUID | None = Field(
        default=None, foreign_key="topic_version.id"
    )
    snapshot: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    project_map: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


class ProjectVersion(SQLModel, table=True):
    __tablename__ = "project_training_version"
    version_id: uuid.UUID = Field(primary_key=True, foreign_key="topic_version.id")
    input_id: uuid.UUID = Field(foreign_key="project_training_input.id")
    snapshot: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


class ProjectMaterials(SQLModel, table=True):
    __tablename__ = "project_training_materials"
    run_id: uuid.UUID = Field(primary_key=True, foreign_key="training_run.id")
    origins: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))


class ProjectRouteFamily(SQLModel, table=True):
    __tablename__ = "project_route_family"
    root_topic_id: uuid.UUID = Field(primary_key=True, foreign_key="topic.id")
    active_version_id: uuid.UUID | None = Field(
        default=None, foreign_key="topic_version.id"
    )


class ProjectRouteUpdate(SQLModel, table=True):
    __tablename__ = "project_route_update"
    topic_id: uuid.UUID = Field(primary_key=True, foreign_key="topic.id")
    root_topic_id: uuid.UUID = Field(
        foreign_key="project_route_family.root_topic_id", index=True
    )
    previous_version_id: uuid.UUID = Field(
        foreign_key="project_training_version.version_id"
    )
