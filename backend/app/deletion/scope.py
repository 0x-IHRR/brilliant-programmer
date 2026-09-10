"""Relationship inventory for a single owner's explicitly chosen object.

Only identifiers leave the inventory. The transient row values are used for
preview compare-and-swap and are never stored in a receipt or application log.
"""

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy import Table
from sqlmodel import Session, SQLModel, col, select

from app.core.config import settings
from app.deletion.fields import FIELDS, HISTORY_FIELDS
from app.project.models import ProjectRun
from app.project.training_models import (
    ProjectInput,
    ProjectMaterials,
    ProjectRouteFamily,
    ProjectTopic,
    ProjectVersion,
)
from app.training.concept_models import ConceptHelp, HelpDelivery
from app.training.draft_collection import DraftCollection
from app.training.draft_models import TrainingDraft
from app.training.evaluation_models import Evaluation
from app.training.independent_models import IndependentWork
from app.training.jd_models import JDAnalysis, JDDocument, JDRoute
from app.training.models import TrainingRun
from app.training.practice_models import PracticeDraft
from app.training.review_models import ScoreReview
from app.training.submission_models import Submission
from app.training.topic_models import Topic, TopicCase, TopicJob, TopicVersion

Kind = Literal["training", "topic", "project"]


def table_of(row: SQLModel) -> Table:
    return SQLModel.metadata.tables[str(row.__tablename__)]


def key_of(row: SQLModel) -> str:
    return ":".join(
        str(getattr(row, c.name)) for c in table_of(row).primary_key.columns
    )


@dataclass
class Patch:
    row: SQLModel
    cleared: dict[str, Any]


@dataclass
class Scope:
    kind: Kind
    target_id: uuid.UUID
    roots: dict[str, set[uuid.UUID]] = field(
        default_factory=lambda: {"training": set(), "topic": set(), "project": set()}
    )
    dependent_runs: set[uuid.UUID] = field(default_factory=set)
    seen: set[uuid.UUID] = field(default_factory=set)
    pointers: list[ProjectRouteFamily] = field(default_factory=list)
    patches: dict[tuple[str, str], Patch] = field(default_factory=dict)

    def add(self, row: SQLModel, fields: dict[str, Any] | None = None) -> None:
        table = table_of(row).name
        key = (table, key_of(row))
        previous = self.patches.get(key)
        cleared = (previous.cleared if previous else {}) | (
            FIELDS[table] if fields is None else fields
        )
        self.patches[key] = Patch(row, cleared)

    def digest(self) -> str:
        raw = json.dumps(
            {
                "kind": self.kind,
                "target_id": str(self.target_id),
                "roots": {k: sorted(map(str, v)) for k, v in self.roots.items()},
                "dependent": sorted(map(str, self.dependent_runs)),
                "pointers": [p.model_dump(mode="json") for p in self.pointers],
                "rows": [
                    (key, p.cleared, p.row.model_dump(mode="json"))
                    for key, p in sorted(self.patches.items())
                ],
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        # A receipt digest must not be a public offline oracle for short JD text.
        return hmac.new(settings.SECRET_KEY.encode(), raw, hashlib.sha256).hexdigest()


def references(value: Any, identities: set[str]) -> bool:
    """Exact persisted IDs, including legacy JSON-encoded comparison payloads."""
    if isinstance(value, str):
        if value in identities:
            return True
        if value.startswith(("{", "[")):
            try:
                return references(json.loads(value), identities)
            except ValueError:
                return False
        return False
    if isinstance(value, dict):
        return any(references(v, identities) for v in value.values())
    if isinstance(value, list):
        return any(references(v, identities) for v in value)
    return False


def collect(
    session: Session, user_id: uuid.UUID, kind: Kind, identity: uuid.UUID
) -> Scope:
    runs = list(
        session.exec(select(TrainingRun).where(TrainingRun.user_id == user_id)).all()
    )
    projects = list(
        session.exec(select(ProjectRun).where(ProjectRun.user_id == user_id)).all()
    )
    topics = list(session.exec(select(Topic).where(Topic.user_id == user_id)).all())
    pool: dict[str, list[Any]] = {
        "training": runs,
        "project": projects,
        "topic": topics,
    }
    if not any(r.id == identity for r in pool[kind]):
        raise HTTPException(404, "所选资料不存在或不属于当前账号")
    scope = Scope(kind, identity)
    scope.roots[kind].add(identity)
    all_topic_ids = {t.id for t in topics}
    project_ids = scope.roots["project"]
    topic_ids = scope.roots["topic"]
    run_ids = scope.roots["training"]
    # Copies reused from this exact project analysis are still this source. A
    # different source/version in the same family is not automatically selected.
    if kind == "project":
        changed = True
        while changed:
            before = len(project_ids)
            project_ids.update(
                p.id for p in projects if p.reused_from_id in project_ids
            )
            changed = len(project_ids) != before
        for binding in session.exec(
            select(ProjectTopic).where(col(ProjectTopic.topic_id).in_(all_topic_ids))
        ).all():
            if (
                binding.topic_id in all_topic_ids
                and binding.project_run_id in project_ids
            ):
                topic_ids.add(binding.topic_id)
    jobs = list(session.exec(select(TopicJob).where(TopicJob.user_id == user_id)).all())
    versions = [
        v
        for v in session.exec(
            select(TopicVersion).where(col(TopicVersion.topic_id).in_(topic_ids))
        ).all()
        if v.topic_id in topic_ids
    ]
    version_ids = {v.id for v in versions}
    scope.pointers = list(
        session.exec(
            select(ProjectRouteFamily)
            .where(
                col(ProjectRouteFamily.root_topic_id).in_(all_topic_ids),
                col(ProjectRouteFamily.active_version_id).in_(version_ids),
            )
            .order_by(col(ProjectRouteFamily.root_topic_id))
        ).all()
    )
    job_ids = {j.id for j in jobs if j.topic_id in topic_ids}
    for run in runs:
        if str(run.selection.get("topic_id")) in set(map(str, topic_ids)):
            run_ids.add(run.id)
        if references(run.selection.get("project"), set(map(str, project_ids))):
            run_ids.add(run.id)
    for run in runs:
        if run.id in run_ids:
            scope.add(run)
            if run.candidate is not None:
                scope.seen.add(run.id)
    for p in projects:
        if p.id in project_ids:
            scope.add(p)
    for job in jobs:
        if job.id in job_ids:
            scope.add(job)
    for version in versions:
        scope.add(version)
    # Foreign keys select only rows of the already verified owner roots.
    for model, fk, ids in (
        (Submission, "run_id", run_ids),
        (Evaluation, "run_id", run_ids),
        (ConceptHelp, "run_id", run_ids),
        (HelpDelivery, "run_id", run_ids),
        (TrainingDraft, "run_id", run_ids),
        (PracticeDraft, "run_id", run_ids),
        (DraftCollection, "run_id", run_ids),
        (ScoreReview, "run_id", run_ids),
        (TopicCase, "run_id", run_ids),
        (ProjectMaterials, "run_id", run_ids),
        (JDDocument, "topic_id", topic_ids),
        (ProjectInput, "topic_id", topic_ids),
        (JDAnalysis, "document_id", job_ids),
        (JDRoute, "version_id", version_ids),
        (ProjectVersion, "version_id", version_ids),
    ):
        for row in session.exec(
            select(model).where(col(getattr(model, fk)).in_(ids))
        ).all():
            scope.add(row)
    owner_runs = {r.id for r in runs}
    deleted_ids = set(map(str, run_ids))
    for work in session.exec(
        select(IndependentWork).where(col(IndependentWork.run_id).in_(owner_runs))
    ).all():
        if work.run_id not in owner_runs:
            continue
        if work.run_id in run_ids:
            scope.add(work)
        elif (
            references(work.history, deleted_ids)
            or references(work.history_snapshot, deleted_ids)
            or references(work.comparison_plan, deleted_ids)
        ):
            scope.add(work, HISTORY_FIELDS)
            scope.dependent_runs.add(work.run_id)
    from app.deletion.quality import attach

    attach(session, user_id, scope)
    return scope
