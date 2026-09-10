"""No administrator override and no client-controlled table or field selectors."""

import uuid
from datetime import datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, SecretStr
from sqlmodel import select

from app.api.deps import SessionDep, get_training_user
from app.api.rate_limit import protect_auth
from app.deletion.models import ArchivedObject, DeletionRequest, ErasedObject
from app.deletion.scope import Kind, Scope, collect
from app.deletion.service import erase, preview
from app.model_config.service import lock_owner
from app.models import User
from app.project.models import ProjectRun
from app.training.draft_schema import JsonUUID
from app.training.models import TrainingRun
from app.training.schema import Strict
from app.training.topic_models import Topic

router = APIRouter(prefix="/records", tags=["records"])
VerifiedUser = Annotated[User, Depends(get_training_user)]


class Record(BaseModel):
    kind: Kind
    id: uuid.UUID
    label: str
    created_at: datetime
    archived: bool
    deleted: bool


class PreviewRequest(Strict):
    kind: Kind
    target_id: JsonUUID
    password: SecretStr = Field(min_length=1, max_length=128)


class ConfirmDeletion(Strict):
    confirmation: Literal["永久删除所列资料及副本"]


class DeletionPublic(BaseModel):
    id: uuid.UUID
    kind: str
    target_id: uuid.UUID
    completed_at: datetime | None
    expires_at: datetime


class PreviewPublic(DeletionPublic):
    objects: dict[str, list[uuid.UUID]]
    comparison_only_runs: list[uuid.UUID]
    private_rows: dict[str, int]
    project_current_pointers_cleared: list[uuid.UUID]
    shared_attachment_candidates: int
    affects_seen_history: bool
    consequences: list[str]


def describe(request: DeletionRequest, scope: Scope) -> PreviewPublic:
    counts: dict[str, int] = {}
    for table, _ in scope.patches:
        counts[table] = counts.get(table, 0) + 1
    from app.deletion.quality import hashes

    attachments = {
        sha
        for (table, _), patch in scope.patches.items()
        if table == "quality_report" and patch.row.model_dump()["report"]
        for sha in hashes(patch.row.model_dump()["report"])
    }
    return PreviewPublic(
        **request.model_dump(),
        objects={k: sorted(v) for k, v in scope.roots.items()},
        comparison_only_runs=sorted(scope.dependent_runs),
        private_rows=counts,
        project_current_pointers_cleared=[p.root_topic_id for p in scope.pointers],
        shared_attachment_candidates=len(attachments),
        affects_seen_history=bool(scope.seen),
        consequences=[
            "所列来源与直接关联记录的原文、私有快照、草稿、帮助和评分副本将永久清除，无法撤销。",
            "仅依赖历史比较的后续轮次保留自己的题面和原答，但删除比较副本并标证据不可用；不作为新的解锁依据。",
            "既有修为、等级、已开放学习入口及无原文的序号、用量和删除标记保留；不会把缺资料判成能力失败。",
            "若删除已见题，完整历史将无法再核验陌生性，后续独立检验会明确退出；普通练习仍可继续。",
            "这里只删除本账号在线私有副本；不删除公开上游或其他账号仍有效引用的原件。备份退出和恢复运营流程另行验证。",
        ],
    )


@router.get("", response_model=list[Record])
def records(
    session: SessionDep, user: VerifiedUser, response: Response
) -> list[Record]:
    response.headers["Cache-Control"] = "no-store"
    archived = {
        (r.kind, r.object_id)
        for r in session.exec(
            select(ArchivedObject).where(ArchivedObject.user_id == user.id)
        ).all()
    }
    erased = {
        (r.kind, r.object_id)
        for r in session.exec(
            select(ErasedObject).where(ErasedObject.user_id == user.id)
        ).all()
    }
    result = []
    for kind, model in (
        ("training", TrainingRun),
        ("project", ProjectRun),
        ("topic", Topic),
    ):
        for row in session.exec(select(model).where(model.user_id == user.id)).all():
            data = row.model_dump()
            result.append(
                Record(
                    kind=cast(Kind, kind),
                    id=data["id"],
                    label={
                        "training": "学习轮次",
                        "topic": "路线与来源（全部版本）",
                        "project": "固定版本项目来源",
                    }[kind],
                    created_at=data["created_at"],
                    archived=(kind, data["id"]) in archived,
                    deleted=(kind, data["id"]) in erased,
                )
            )
    return sorted(result, key=lambda r: (r.created_at, str(r.id)), reverse=True)


@router.post(
    "/deletions/preview",
    response_model=PreviewPublic,
    dependencies=[Depends(protect_auth)],
)
def deletion_preview(
    body: PreviewRequest, session: SessionDep, user: VerifiedUser, response: Response
) -> PreviewPublic:
    response.headers["Cache-Control"] = "no-store"
    request, scope = preview(
        session, user.id, body.kind, body.target_id, body.password.get_secret_value()
    )
    return describe(request, scope)


@router.post("/deletions/{identity}/confirm", response_model=DeletionPublic)
def confirm_deletion(
    identity: uuid.UUID,
    _body: ConfirmDeletion,
    session: SessionDep,
    user: VerifiedUser,
    response: Response,
) -> DeletionPublic:
    response.headers["Cache-Control"] = "no-store"
    return DeletionPublic.model_validate(erase(session, user.id, identity).model_dump())


@router.get("/deletions/{identity}", response_model=DeletionPublic)
def deletion_receipt(
    identity: uuid.UUID, session: SessionDep, user: VerifiedUser, response: Response
) -> DeletionPublic:
    response.headers["Cache-Control"] = "no-store"
    row = session.get(DeletionRequest, identity)
    if not row or row.user_id != user.id:
        raise HTTPException(404, "删除记录不存在")
    return DeletionPublic.model_validate(row.model_dump())


class ArchiveRequest(Strict):
    kind: Kind
    target_id: JsonUUID
    archived: bool


@router.post("/archive", status_code=204)
def archive(body: ArchiveRequest, session: SessionDep, user: VerifiedUser) -> None:
    lock_owner(session, user.id)
    collect(session, user.id, body.kind, body.target_id)
    row = session.get(ArchivedObject, (user.id, body.kind, body.target_id))
    if body.archived and not row:
        session.add(
            ArchivedObject(user_id=user.id, kind=body.kind, object_id=body.target_id)
        )
    elif not body.archived and row:
        session.delete(row)
    session.commit()
