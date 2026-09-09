"""Pure decisions for one owned original/practice draft scope.

Integration must authenticate ownership, load this scope and latest submission
under the existing User -> run lock, and commit the returned state atomically.
No decision writes formal answers, help, seen facts, awards or qualification.
A returned snapshot is only a proposed receipt until that commit succeeds.
The API must persist conflicts before reporting them, not roll them back on 409.
"""

import uuid
from dataclasses import dataclass, replace
from datetime import datetime

from fastapi import HTTPException

from app.training.draft_save import same_progress
from app.training.draft_schema import (
    DraftProgress,
    DraftSnapshot,
    SaveDraft,
    validate_progress,
)
from app.training.schema import Candidate


@dataclass(frozen=True)
class DraftVersions:
    run_id: uuid.UUID
    help_id: uuid.UUID | None
    revision: uuid.UUID
    generation: uuid.UUID
    versions: tuple[DraftSnapshot, ...] = ()
    current: uuid.UUID | None = None
    unresolved: tuple[uuid.UUID, ...] = ()


def new_versions(run_id: uuid.UUID, help_id: uuid.UUID | None = None) -> DraftVersions:
    # Persist this empty scope before giving devices its generation token.
    return DraftVersions(run_id, help_id, uuid.uuid4(), uuid.uuid4())


def save_version(
    state: DraftVersions,
    *,
    candidate: Candidate,
    request: SaveDraft,
    observed_revision: uuid.UUID,
    generation: uuid.UUID,
    latest_submission_id: uuid.UUID | None,
    saved_at: datetime,
) -> tuple[DraftVersions, DraftSnapshot]:
    """Append competing input; never select a winner when a conflict exists.

    The returned snapshot can be an older idempotent receipt. Callers must use
    state.current/unresolved, not that receipt, to render the current selection.
    """
    validate_progress(candidate, request.progress)
    if saved_at.tzinfo is None:
        raise ValueError("save time must be server timezone-aware")
    if generation != state.generation:
        raise HTTPException(
            409, "草稿已删除或重新开始；输入保留，请重新读取后明确继续。"
        )
    for version in state.versions:
        if version.request_id == request.request_id:
            if not same_progress(version.progress, request.progress):
                raise HTTPException(409, "保存请求标识已用于其他输入，当前输入保留。")
            return state, version.model_copy(deep=True)
    if request.progress.based_on_submission_id != latest_submission_id:
        raise HTTPException(409, "正式提交记录已变化，当前输入保留；请读取后继续。")
    snapshot = DraftSnapshot(
        run_id=state.run_id,
        version=uuid.uuid4(),
        request_id=request.request_id,
        saved_at=saved_at,
        progress=request.progress.model_copy(deep=True),
    )
    conflict = bool(state.unresolved) or (
        request.expected_version != state.current or observed_revision != state.revision
    )
    unresolved = state.unresolved
    if conflict:
        if not unresolved and state.current is not None:
            unresolved = (state.current,)
        unresolved += (snapshot.version,)
    result = replace(
        state,
        revision=uuid.uuid4(),
        versions=(*state.versions, snapshot),
        current=state.current if conflict else snapshot.version,
        unresolved=unresolved,
    )
    return result, snapshot.model_copy(deep=True)


def choose_version(
    state: DraftVersions, *, observed_revision: uuid.UUID, version: uuid.UUID
) -> DraftVersions:
    """Choose one whole retained snapshot from the confirmed server collection."""
    if observed_revision != state.revision:
        raise HTTPException(409, "草稿版本集合已变化，请重新查看全部版本后选择。")
    if not any(item.version == version for item in state.versions):
        raise HTTPException(409, "所选草稿版本已不存在，请重新读取。")
    return replace(state, revision=uuid.uuid4(), current=version, unresolved=())


def delete_current(
    state: DraftVersions, *, observed_revision: uuid.UUID, version: uuid.UUID
) -> DraftVersions:
    """Delete only the specified current payload; retain all other versions.

    The rotated generation is a persistent tombstone: pre-delete devices cannot
    resurrect a removed draft, including their first save with expected None.
    A failed/lost deletion response is reconciled by reading the server state.
    """
    if observed_revision != state.revision or version != state.current:
        raise HTTPException(409, "当前草稿或版本集合已变化；未删除，请重新查看。")
    return replace(
        state,
        revision=uuid.uuid4(),
        generation=uuid.uuid4(),
        current=None,
        versions=tuple(item for item in state.versions if item.version != version),
        unresolved=tuple(item for item in state.unresolved if item != version),
    )


def require_resolved(state: DraftVersions) -> None:
    """Both original and practice submit APIs must call under their run lock."""
    if state.unresolved:
        raise HTTPException(409, "草稿冲突尚未解决，请先查看全部版本并选择后再交卷。")


def differing_fields(left: DraftProgress, right: DraftProgress) -> tuple[str, ...]:
    """Stable-ID differences only; the UI displays each full snapshot separately."""
    fields = []
    if left.step != right.step:
        fields.append("step")
    if left.based_on_submission_id != right.based_on_submission_id:
        fields.append("based_on_submission_id")
    a = {item.judgment_id: item for item in left.answers}
    b = {item.judgment_id: item for item in right.answers}
    fields.extend(
        f"answers.{key}"
        for key in sorted(a.keys() | b.keys())
        if a.get(key) != b.get(key)
    )
    return tuple(fields)
