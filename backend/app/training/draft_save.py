"""Pure save decision; the API must commit it under the run's submission lock.

The caller authenticates ownership, loads current draft and latest submission in
that same transaction, then persists only the returned draft. This helper neither
commits nor creates submissions, help, evaluation, awards, or expiry timestamps.
A 409 preserves the stored snapshot; the caller must retain the unsaved input.
"""

import uuid
from datetime import datetime

from fastapi import HTTPException

from app.training.draft_schema import (
    DraftProgress,
    DraftSnapshot,
    SaveDraft,
    validate_progress,
)
from app.training.schema import Candidate


def same_progress(left: DraftProgress, right: DraftProgress) -> bool:
    def comparable(progress: DraftProgress) -> dict[str, object]:
        return {
            "step": progress.step,
            "based_on_submission_id": progress.based_on_submission_id,
            "answers": {a.judgment_id: a.model_dump() for a in progress.answers},
        }

    return comparable(left) == comparable(right)


def prepare_save(
    *,
    run_id: uuid.UUID,
    candidate: Candidate,
    current: DraftSnapshot | None,
    request: SaveDraft,
    latest_submission_id: uuid.UUID | None,
    saved_at: datetime,
) -> DraftSnapshot:
    validate_progress(candidate, request.progress)
    if saved_at.tzinfo is None:
        raise ValueError("save time must be server timezone-aware")
    if current is not None and current.run_id != run_id:
        raise ValueError("draft belongs to a different run")
    if request.progress.based_on_submission_id != latest_submission_id:
        raise HTTPException(
            409, "正式提交记录已变化，当前输入保留；请读取记录后再继续编辑。"
        )
    if current is not None and current.request_id == request.request_id:
        if same_progress(current.progress, request.progress):
            return current  # Lost-response retry does not create a new revision.
        raise HTTPException(409, "保存请求标识已用于其他输入，当前输入保留。")
    if request.expected_version != (current.version if current else None):
        raise HTTPException(
            409, "草稿已有其他版本，当前输入保留；请读取并比较，不能自动覆盖。"
        )
    return DraftSnapshot(
        run_id=run_id,
        version=uuid.uuid4(),
        request_id=request.request_id,
        saved_at=saved_at,
        progress=request.progress.model_copy(deep=True),
    )
