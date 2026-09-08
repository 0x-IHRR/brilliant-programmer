"""Editable progress is separate from immutable submission and completion facts."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from app.training.schema import Candidate, Strict, Text

DraftText = Annotated[str, Field(max_length=6000)]


class DraftAnswer(Strict):
    judgment_id: Text
    value: int | list[int] | DraftText | None = None
    reason: DraftText = ""


class DraftProgress(Strict):
    answers: list[DraftAnswer] = Field(default_factory=list, max_length=4)
    step: Literal["materials", "judgments", "coach"] = "materials"
    # An editor for an original answer and an editor for a supplement are distinct.
    based_on_submission_id: uuid.UUID | None = None


class SaveDraft(Strict):
    request_id: uuid.UUID
    expected_version: uuid.UUID | None
    progress: DraftProgress


class DraftSnapshot(Strict):
    run_id: uuid.UUID
    version: uuid.UUID
    request_id: uuid.UUID
    saved_at: datetime
    progress: DraftProgress


def validate_progress(candidate: Candidate, progress: DraftProgress) -> None:
    judgments = {item.id: item for item in candidate.judgments}
    ids = [answer.judgment_id for answer in progress.answers]
    if len(set(ids)) != len(ids) or not set(ids) <= judgments.keys():
        raise ValueError("草稿含重复或未知判断")
    for answer in progress.answers:
        judgment = judgments[answer.judgment_id]
        value = answer.value
        if value is None or value == "":
            continue
        if judgment.kind == "choice":
            valid = type(value) is int and 0 <= value < len(judgment.options)
        elif judgment.kind == "order":
            # The current UI uses -1 for empty slots. Duplicate selections and
            # incomplete lists are editable intermediate states, not submissions.
            valid = (
                isinstance(value, list)
                and len(value) <= len(judgment.options)
                and all(
                    type(i) is int and -1 <= i < len(judgment.options) for i in value
                )
            )
        else:
            valid = isinstance(value, str)
        if not valid:
            raise ValueError("草稿判断值不属于当前题型或选项")
