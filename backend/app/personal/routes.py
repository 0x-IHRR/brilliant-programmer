"""One owned snapshot for review and export; no publication or learning writes."""

import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel
from sqlmodel import Session, col, select

from app.capabilities.evidence import EvidenceMap
from app.capabilities.evidence_service import read_evidence
from app.deletion.models import ArchivedObject, ErasedObject
from app.models import User
from app.project.models import ProjectRun
from app.project.routes import ProjectPublic
from app.project.routes import view as project_view
from app.project.training_models import ProjectTopic
from app.project.training_routes import ProjectTrainingPublic
from app.project.training_routes import view as project_route_view
from app.training.boss_models import BossPromotion
from app.training.boss_routes import RevalidationPublic, revalidation_view
from app.training.boss_service import revalidations
from app.training.concept_models import ConceptHelp, HelpDelivery
from app.training.concepts import HelpPublic
from app.training.concepts import view as help_view
from app.training.draft_collection import CollectionView, DraftCollection
from app.training.draft_models import TrainingDraft
from app.training.draft_schema import DraftSnapshot
from app.training.evaluation_models import Evaluation
from app.training.evaluations import EvaluationPublic
from app.training.evaluations import _view as evaluation_view
from app.training.guided import practice_case
from app.training.jd_models import JDTopic
from app.training.jds import JDPublic
from app.training.jds import view as jd_view
from app.training.models import TrainingRun
from app.training.practice_models import PracticeDraft
from app.training.practices import PracticeState, exercise_for
from app.training.projection import read_snapshot
from app.training.review_models import ReviewAward, ScoreReview
from app.training.review_service import points
from app.training.reviews import ReviewPublic
from app.training.reviews import view as review_view
from app.training.routes import TaskPublic, VerifiedUser
from app.training.routes import view as task_view
from app.training.schema import Candidate, Source
from app.training.submission_models import PracticeAward
from app.training.submission_schema import SubmissionState
from app.training.submissions import _state
from app.training.topic_models import Topic
from app.training.topics import TopicPublic
from app.training.topics import _public as topic_view

router = APIRouter(prefix="/personal-review", tags=["personalreview"])


class DraftHistory(BaseModel):
    help_id: uuid.UUID | None
    versions: list[DraftSnapshot]
    current: uuid.UUID | None
    unresolved: list[uuid.UUID]


class RoundHistory(BaseModel):
    entry: str
    created_at: datetime
    archived: bool
    task: TaskPublic
    submissions: SubmissionState
    evaluation: EvaluationPublic | None
    review: ReviewPublic | None
    help: list[HelpPublic]
    practice_submissions: dict[str, SubmissionState]
    drafts: list[DraftHistory]
    practices: list[PracticeState]


class RewardHistory(BaseModel):
    kind: Literal["completion", "review_difference"]
    run_id: uuid.UUID
    points: int
    rule_version: str
    created_at: datetime


class PromotionHistory(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    original_id: uuid.UUID
    stage_version: str
    from_level: str
    to_level: str
    created_at: datetime


class ObjectMark(BaseModel):
    kind: str
    object_id: uuid.UUID


class PersonalReview(BaseModel):
    format_version: str = "personal-review-v1"
    read_at: datetime
    user_id: uuid.UUID
    level: str
    total_points: int
    rounds: list[RoundHistory]
    topics: list[TopicPublic]
    jds: list[JDPublic]
    project_routes: list[ProjectTrainingPublic]
    projects: list[ProjectPublic]
    evidence: EvidenceMap
    rewards: list[RewardHistory]
    promotions: list[PromotionHistory]
    revalidations: list[RevalidationPublic]
    archived: list[ObjectMark]
    deleted: list[ObjectMark]


def drafts(session: Session, run_id: uuid.UUID) -> list[DraftHistory]:
    # Do not call draft_collection.load: it creates a collection on first read.
    result = []
    scopes: set[uuid.UUID | None] = set()
    for collection in session.exec(
        select(DraftCollection)
        .where(DraftCollection.run_id == run_id)
        .order_by(col(DraftCollection.scope_key))
    ).all():
        value = CollectionView.model_validate_json(json.dumps(collection.data))
        scopes.add(collection.help_id)
        result.append(
            DraftHistory(
                help_id=collection.help_id,
                versions=value.versions,
                current=value.current,
                unresolved=value.unresolved,
            )
        )
    legacy = session.get(TrainingDraft, run_id)
    if legacy and None not in scopes:
        original = DraftSnapshot.model_validate_json(legacy.model_dump_json())
        result.append(
            DraftHistory(
                help_id=None,
                versions=[original],
                current=original.version,
                unresolved=[],
            )
        )
    for practice in session.exec(
        select(PracticeDraft)
        .where(PracticeDraft.run_id == run_id)
        .order_by(col(PracticeDraft.help_id))
    ).all():
        if practice.help_id not in scopes:
            saved = DraftSnapshot.model_validate_json(
                practice.model_dump_json(exclude={"help_id"})
            )
            result.append(
                DraftHistory(
                    help_id=practice.help_id,
                    versions=[saved],
                    current=saved.version,
                    unresolved=[],
                )
            )
    return result


def practice_history(
    session: Session, run: TrainingRun, helps: Sequence[ConceptHelp]
) -> list[PracticeState]:
    result = []
    for item in helps:
        delivered = session.exec(
            select(HelpDelivery.id).where(
                HelpDelivery.help_id == item.id, HelpDelivery.status == "delivered"
            )
        ).first()
        if item.kind != "demonstration" or item.status != "ready" or not delivered:
            continue
        _, exercise = exercise_for(session, run.id, item.id, run.user_id)
        records = _state(session, run.id, run.user_id, item.id)
        result.append(
            PracticeState(
                help_id=item.id,
                exercise=practice_case(
                    Candidate.model_validate(run.candidate),
                    [Source.model_validate(s) for s in run.sources],
                    exercise.judgments[0].id,
                    "",
                ),
                records=records,
                completed=any(s.status == "completed" for s in records.submissions),
            )
        )
    return result


def build_personal_review(session: Session, user_id: uuid.UUID) -> PersonalReview:
    # Ponytail: retain the existing personal-history projection, including its
    # cumulative evidence comparisons. No cache, truncation, or expiry; measure
    # actual history size/latency before adding an incremental representation.
    user = session.get(User, user_id)
    assert user is not None
    erased = session.exec(
        select(ErasedObject).where(ErasedObject.user_id == user_id)
    ).all()
    deleted = {(r.kind, r.object_id) for r in erased}
    archived = session.exec(
        select(ArchivedObject).where(ArchivedObject.user_id == user_id)
    ).all()
    archived_keys = {(r.kind, r.object_id) for r in archived}
    rounds = []
    for run in session.exec(
        select(TrainingRun)
        .where(TrainingRun.user_id == user_id)
        .order_by(col(TrainingRun.created_at), col(TrainingRun.id))
    ).all():
        if ("training", run.id) in deleted:
            continue
        helps = session.exec(
            select(ConceptHelp)
            .where(ConceptHelp.run_id == run.id)
            .order_by(col(ConceptHelp.created_sequence))
        ).all()
        evaluation = session.get(Evaluation, run.id)
        review = session.get(ScoreReview, run.id)
        rounds.append(
            RoundHistory(
                entry=run.selection.get("entry", "random"),
                created_at=run.created_at,
                archived=("training", run.id) in archived_keys,
                task=task_view(session, run),
                submissions=_state(session, run.id, user_id, None),
                evaluation=evaluation_view(session, evaluation) if evaluation else None,
                review=review_view(session, review) if review else None,
                help=[help_view(session, item) for item in helps],
                practice_submissions={
                    str(item.id): _state(session, run.id, user_id, item.id)
                    for item in helps
                    if item.kind == "demonstration"
                },
                drafts=drafts(session, run.id),
                practices=practice_history(session, run, helps),
            )
        )
    topics, jds, project_routes = [], [], []
    for topic in session.exec(
        select(Topic)
        .where(Topic.user_id == user_id)
        .order_by(col(Topic.created_at), col(Topic.id))
    ).all():
        if ("topic", topic.id) in deleted:
            continue
        if session.get(JDTopic, topic.id):
            jds.append(jd_view(session, topic))
        elif session.get(ProjectTopic, topic.id):
            project_routes.append(project_route_view(session, topic))
        else:
            topics.append(topic_view(session, topic))
    rewards = [
        RewardHistory(
            kind="completion",
            **r.model_dump(include={"run_id", "points", "rule_version", "created_at"}),
        )
        for r in session.exec(
            select(PracticeAward).where(PracticeAward.user_id == user_id)
        ).all()
    ]
    rewards.extend(
        RewardHistory(
            kind="review_difference",
            **r.model_dump(include={"run_id", "points", "rule_version", "created_at"}),
        )
        for r in session.exec(
            select(ReviewAward).where(ReviewAward.user_id == user_id)
        ).all()
    )
    return PersonalReview(
        read_at=datetime.now(UTC),
        user_id=user_id,
        level=user.level,
        total_points=points(session, user_id),
        rounds=rounds,
        topics=topics,
        jds=jds,
        project_routes=project_routes,
        projects=[
            project_view(session, item)
            for item in session.exec(
                select(ProjectRun)
                .where(ProjectRun.user_id == user_id)
                .order_by(col(ProjectRun.created_at), col(ProjectRun.id))
            ).all()
            if ("project", item.id) not in deleted
        ],
        evidence=read_evidence(session, user_id),
        rewards=sorted(rewards, key=lambda r: (r.created_at, str(r.run_id), r.kind)),
        promotions=[
            PromotionHistory.model_validate(r, from_attributes=True)
            for r in session.exec(
                select(BossPromotion).where(BossPromotion.user_id == user_id)
            ).all()
        ],
        revalidations=[
            revalidation_view(session, r) for r in revalidations(session, user_id)
        ],
        archived=[ObjectMark(kind=r.kind, object_id=r.object_id) for r in archived],
        deleted=[ObjectMark(kind=r.kind, object_id=r.object_id) for r in erased],
    )


@router.get("")
def read_personal_review(user: VerifiedUser, response: Response) -> PersonalReview:
    response.headers["Cache-Control"] = "no-store"
    with read_snapshot(user.id) as session:
        return build_personal_review(session, user.id)


@router.get("/export", response_model=PersonalReview)
def export_personal_review(user: VerifiedUser) -> Response:
    # Build and serialize under the SAME snapshot/erasure guard, no nested read
    # wrappers or streaming queries after the snapshot has closed.
    with read_snapshot(user.id) as session:
        payload = build_personal_review(session, user.id).model_dump_json(indent=2)
        return Response(
            payload,
            media_type="application/json",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": 'attachment; filename="personal-learning.json"',
                "X-Content-Type-Options": "nosniff",
            },
        )
