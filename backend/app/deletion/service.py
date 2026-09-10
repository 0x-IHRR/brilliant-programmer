"""Explicit password-bound preview, owner serialization and exact-scope erase."""

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.config import settings
from app.core.security import verify_password
from app.deletion.models import DeletionRequest, ErasedObject, ErasedRow
from app.deletion.scope import Kind, Scope, collect
from app.model_config.service import lock_owner
from app.quality.models import QualityReport


def authentication_digest(hashed_password: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode(), hashed_password.encode(), hashlib.sha256
    ).hexdigest()


def require_available(
    session: Session, user_id: uuid.UUID, kind: str, identity: uuid.UUID
) -> None:
    if session.get(ErasedObject, (user_id, kind, identity)):
        raise HTTPException(
            410, "所选资料已永久删除；保留的奖励、等级和开放事实不受影响"
        )


def preview(
    session: Session, user_id: uuid.UUID, kind: Kind, identity: uuid.UUID, password: str
) -> tuple[DeletionRequest, Scope]:
    user = lock_owner(session, user_id)
    valid, _ = verify_password(password, user.hashed_password)
    if not valid:
        raise HTTPException(403, "重新认证失败，请核对当前密码")
    require_available(session, user_id, kind, identity)
    scope = collect(session, user_id, kind, identity)
    request = DeletionRequest(
        user_id=user_id,
        kind=kind,
        target_id=identity,
        scope_digest=scope.digest(),
        authentication_digest=authentication_digest(user.hashed_password),
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    session.add(request)
    session.commit()
    session.refresh(request)
    return request, scope


def erase(session: Session, user_id: uuid.UUID, identity: uuid.UUID) -> DeletionRequest:
    user = lock_owner(session, user_id)
    from sqlalchemy import text

    from app.training.projection import erasure_lock_key

    session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": erasure_lock_key(user_id)}
    )
    request = session.exec(
        select(DeletionRequest)
        .where(DeletionRequest.id == identity, DeletionRequest.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one_or_none()
    if not request:
        raise HTTPException(404, "删除预览不存在")
    if request.completed_at:
        return request
    if request.expires_at <= datetime.now(
        UTC
    ) or request.authentication_digest != authentication_digest(user.hashed_password):
        raise HTTPException(409, "重新认证已失效，请重新预览删除范围")
    if request.kind not in {"training", "project", "topic"}:
        raise HTTPException(409, "删除范围不可用")
    scope = collect(session, user_id, request.kind, request.target_id)  # type: ignore[arg-type]
    if not hmac.compare_digest(scope.digest(), request.scope_digest):
        raise HTTPException(409, "资料或关联范围已变化，尚未删除；请重新预览并确认")
    from app.deletion.quality import binding_digest
    from app.quality.rules import Report

    for kind, identities in scope.roots.items():
        for object_id in sorted(identities):
            if not session.get(ErasedObject, (user_id, kind, object_id)):
                session.add(
                    ErasedObject(
                        user_id=user_id,
                        kind=kind,
                        object_id=object_id,
                        request_id=request.id,
                        seen=object_id in scope.seen,
                        binding_digest=binding_digest(
                            Report.model_validate_json(
                                json.dumps(
                                    cast(
                                        QualityReport,
                                        scope.patches[
                                            ("quality_report", str(object_id))
                                        ].row,
                                    ).report
                                )
                            ).binding
                        )
                        if kind == "quality"
                        else None,
                    )
                )
    for run_id in sorted(scope.dependent_runs):
        if not session.get(ErasedObject, (user_id, "evidence", run_id)):
            session.add(
                ErasedObject(
                    user_id=user_id,
                    kind="evidence",
                    object_id=run_id,
                    request_id=request.id,
                )
            )
    for (table, key), patch in sorted(scope.patches.items()):
        session.add(
            ErasedRow(
                table_name=table,
                row_key=key,
                user_id=user_id,
                request_id=request.id,
                cleared=patch.cleared,
            )
        )
    from app.deletion.quality import erase_unreferenced, hashes, lock_hashes

    blobs = set()
    for (table, _), patch in scope.patches.items():
        if table == "quality_report" and cast(QualityReport, patch.row).report:
            blobs.update(hashes(cast(QualityReport, patch.row).report))
    from app.deletion.models import ErasedAttachment

    lock_hashes(session, blobs)
    for sha in sorted(blobs):
        session.add(ErasedAttachment(request_id=request.id, sha256=sha))
    session.flush()
    for patch in scope.patches.values():
        for name, value in patch.cleared.items():
            setattr(patch.row, name, value)
        session.add(patch.row)
    session.flush()
    erase_unreferenced(session, blobs)
    for pointer in scope.pointers:
        pointer.active_version_id = None
        session.add(pointer)
    request.completed_at = datetime.now(UTC)
    session.add(request)
    session.commit()
    session.refresh(request)
    return request


def unavailable(session: Session, user_id: uuid.UUID, run_id: uuid.UUID) -> bool:
    return bool(
        session.get(ErasedObject, (user_id, "training", run_id))
        or session.get(ErasedObject, (user_id, "evidence", run_id))
    )


def hidden_ids(session: Session, user_id: uuid.UUID, kind: str) -> set[uuid.UUID]:
    from app.deletion.models import ArchivedObject

    return {
        uuid.UUID(str(r.model_dump()["object_id"]))
        for model in (ErasedObject, ArchivedObject)
        for r in session.exec(
            select(model).where(model.user_id == user_id, model.kind == kind)
        ).all()
    }
