import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.model_config.connection import Attempt
from app.training.schema import Candidate, Strict, Text


class Answer(Strict):
    judgment_id: Text
    value: int | list[int] | Text
    reason: Text


class Submit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID
    expected_config_version: uuid.UUID
    disclosure_accepted: bool
    answers: list[Answer] = Field(min_length=1, max_length=4)
    # Optimistic lineage stops two different devices silently replacing one another.
    previous_submission_id: uuid.UUID | None = None


class RelevanceItem(Strict):
    judgment_id: Text
    status: Literal["related", "unrelated", "unclear"]


class Relevance(Strict):
    items: Annotated[list[RelevanceItem], Field(min_length=1, max_length=4)]


class SubmissionPublic(BaseModel):
    id: uuid.UUID
    sequence: int
    original_id: uuid.UUID | None
    kind: str
    answers: list[Answer]
    created_at: datetime
    config_version: uuid.UUID
    destination: str
    model_id: str
    status: str
    code: str
    message: str
    relevance: list[RelevanceItem]
    neutral_clarification: bool
    attempts: list[Attempt]
    can_retry: bool


class SubmissionState(BaseModel):
    run_id: uuid.UUID
    submissions: list[SubmissionPublic]
    completed_at: datetime | None
    awarded_points: int
    total_points: int
    rule_version: str | None


def validate_answers(candidate: Candidate, answers: list[Answer]) -> None:
    by_id = {answer.judgment_id: answer for answer in answers}
    if len(by_id) != len(answers) or set(by_id) != {j.id for j in candidate.judgments}:
        raise ValueError("请完成每个必答判断与理由，不得重复或新增判断")
    for judgment in candidate.judgments:
        value = by_id[judgment.id].value
        if judgment.kind == "choice":
            valid = type(value) is int and 0 <= value < len(judgment.options)
        elif judgment.kind == "order":
            valid = (
                isinstance(value, list)
                and all(type(i) is int for i in value)
                and sorted(value) == list(range(len(judgment.options)))
            )
        else:
            valid = isinstance(value, str) and bool(value.strip())
        if not valid:
            raise ValueError("请检查点选、完整且不重复的排序或非空预测")
