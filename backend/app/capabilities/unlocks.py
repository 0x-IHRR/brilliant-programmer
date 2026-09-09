"""Published learning units, opened only from owner-locked server evidence."""

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import JSON, Column, DateTime
from sqlmodel import Field, Session, SQLModel, select

from app.capabilities.catalog import CATALOG, EvidenceKey, Level
from app.capabilities.evidence import EvidenceMap
from app.capabilities.evidence_service import read_evidence


class OpenedUnit(SQLModel, table=True):
    __tablename__ = "opened_unit"
    user_id: uuid.UUID = Field(primary_key=True, foreign_key="user.id")
    catalog_version: str = Field(primary_key=True)
    capability_id: str = Field(primary_key=True)
    difficulty: str = Field(primary_key=True)
    background_id: str = Field(primary_key=True)
    opened_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    source: str = "verified_prerequisites"
    evidence_ids: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )


class UnitAccess(BaseModel):
    target: EvidenceKey
    catalog_version: str = CATALOG.version
    opened: bool
    eligible: bool
    missing_required: list[EvidenceKey]
    missing_alternatives: list[list[EvidenceKey]]


def level_for(target: EvidenceKey) -> Level:
    for domain in CATALOG.domains:
        for capability in domain.capabilities:
            if (
                capability.id == target.capability_id
                and capability.background_id == target.background_id
            ):
                return next(
                    level
                    for level in capability.levels
                    if level.difficulty == target.difficulty
                )
    raise HTTPException(422, "能力、难度或技术背景不属于当前发布目录")


def access(target: EvidenceKey, evidence: EvidenceMap, opened: bool) -> UnitAccess:
    level = level_for(target)
    verified = {item.target for item in evidence.states if item.status == "verified"}
    return UnitAccess(
        target=target,
        catalog_version=CATALOG.version,
        opened=opened,
        eligible=opened or level.satisfied_by(verified),
        missing_required=[key for key in level.required if key not in verified],
        missing_alternatives=[
            list(group)
            for group in level.alternatives
            if not any(key in verified for key in group)
        ],
    )


def identity(
    user_id: uuid.UUID, target: EvidenceKey
) -> tuple[uuid.UUID, str, str, str, str]:
    return (
        user_id,
        CATALOG.version,
        target.capability_id,
        target.difficulty,
        target.background_id,
    )


def read_access(session: Session, user_id: uuid.UUID) -> list[UnitAccess]:
    evidence = read_evidence(session, user_id)
    opened = {
        (row.capability_id, row.difficulty, row.background_id)
        for row in session.exec(
            select(OpenedUnit).where(
                OpenedUnit.user_id == user_id,
                OpenedUnit.catalog_version == CATALOG.version,
            )
        ).all()
    }
    return [
        access(
            EvidenceKey(
                capability_id=c.id,
                difficulty=level.difficulty,
                background_id=c.background_id,
            ),
            evidence,
            (c.id, level.difficulty, c.background_id) in opened,
        )
        for domain in CATALOG.domains
        for c in domain.capabilities
        for level in c.levels
    ]


def open_unit(session: Session, user_id: uuid.UUID, target: EvidenceKey) -> UnitAccess:
    """Caller keeps the existing User lock through commit; no points or model."""
    level_for(target)
    previous = session.get(OpenedUnit, identity(user_id, target))
    evidence = read_evidence(session, user_id)
    result = access(target, evidence, bool(previous))
    if not result.eligible:
        raise HTTPException(
            409,
            {
                "message": "当前前置证明尚未满足；这不表示你不会，请选择缺项补练或主动检验。",
                "access": result.model_dump(mode="json"),
            },
        )
    if not previous:
        dependencies = set(level_for(target).required).union(
            *level_for(target).alternatives
        )
        session.add(
            OpenedUnit(
                user_id=user_id,
                catalog_version=CATALOG.version,
                **target.model_dump(),
                evidence_ids=[
                    str(t.evidence.original_id)
                    for s in evidence.states
                    if s.target in dependencies and s.status == "verified"
                    for t in s.history
                    if t.counted
                ],
            )
        )
    return result.model_copy(update={"opened": True})
