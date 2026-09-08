import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.capabilities.catalog import CATALOG, EvidenceKey
from app.training.draft_save import prepare_save
from app.training.draft_schema import (
    DraftAnswer,
    DraftProgress,
    SaveDraft,
    validate_progress,
)
from app.training.schema import Candidate


@pytest.fixture
def candidate():
    return Candidate.model_validate(
        {
            "target": EvidenceKey(
                capability_id="network.delivery",
                difficulty="基础",
                background_id="network-evidence-v1",
            ),
            "catalog_version": CATALOG.version,
            "title": "合成请求",
            "task": "根据材料判断",
            "assumptions": ["教学假设"],
            "evidence": [
                {
                    "id": "e1",
                    "label": "教学材料",
                    "text": "未收到确认",
                    "facts": {"confirmed": "false"},
                    "citations": [{"source_id": "s1", "quote": "reference"}],
                }
            ],
            "judgments": [
                {
                    "id": "choice",
                    "kind": "choice",
                    "prompt": "作选择",
                    "options": ["a", "b"],
                    "evidence_ids": ["e1"],
                },
                {
                    "id": "order",
                    "kind": "order",
                    "prompt": "排顺序",
                    "options": ["a", "b", "c"],
                    "evidence_ids": ["e1"],
                },
                {
                    "id": "prediction",
                    "kind": "prediction",
                    "prompt": "给预测",
                    "options": ["会", "不会"],
                    "evidence_ids": ["e1"],
                },
            ],
            "rubric": [
                {
                    "judgment_id": "choice",
                    "acceptable_options": [0],
                    "reasoning": "hidden",
                    "evidence_ids": ["e1"],
                    "counterexample": "hidden",
                    "help_boundary": "hidden",
                }
            ],
            "variation": {
                "causal_condition": "确认丢失",
                "expected_evidence": "日志",
                "decision_effect": "补证",
            },
            "missing_evidence": [],
            "conflicts": [],
        }
    )


@pytest.mark.parametrize(
    "answers",
    [
        [],
        [DraftAnswer(judgment_id="choice")],
        [DraftAnswer(judgment_id="choice", value="", reason="  ")],
        [DraftAnswer(judgment_id="order", value=[-1, 1, 1])],
        [DraftAnswer(judgment_id="order", value=[2])],
        [DraftAnswer(judgment_id="prediction", value=" \n", reason="")],
    ],
)
def test_draft_accepts_incomplete_editing(candidate, answers):
    validate_progress(candidate, DraftProgress(answers=answers))


@pytest.mark.parametrize(
    "answers",
    [
        [DraftAnswer(judgment_id="unknown")],
        [DraftAnswer(judgment_id="choice"), DraftAnswer(judgment_id="choice")],
        [DraftAnswer(judgment_id="choice", value=-1)],
        [DraftAnswer(judgment_id="choice", value=2)],
        [DraftAnswer(judgment_id="choice", value="1")],
        [DraftAnswer(judgment_id="order", value=[3])],
        [DraftAnswer(judgment_id="order", value=[-2])],
        [DraftAnswer(judgment_id="order", value=[0, 1, 2, -1])],
        [DraftAnswer(judgment_id="prediction", value=1)],
    ],
)
def test_draft_checks_identity_and_type_without_grading(candidate, answers):
    with pytest.raises(ValueError):
        validate_progress(candidate, DraftProgress(answers=answers))


@pytest.mark.parametrize(
    "data",
    [
        {"judgment_id": "choice", "value": True},
        {"judgment_id": "order", "value": [True]},
        {"judgment_id": "prediction", "reason": "x" * 6001},
        {"judgment_id": "choice", "award": 10},
    ],
)
def test_invalid_shape_is_rejected(data):
    with pytest.raises(ValidationError):
        DraftAnswer.model_validate(data)


def test_save_retry_and_stale_device_preserve_snapshot(candidate):
    run_id = uuid.uuid4()
    now = datetime.now(UTC)
    progress = DraftProgress(
        step="judgments",
        answers=[
            DraftAnswer(judgment_id="prediction", value="可能"),
            DraftAnswer(judgment_id="order", value=[-1, 1, 1]),
        ],
    )
    request = SaveDraft(
        request_id=uuid.uuid4(), expected_version=None, progress=progress
    )

    def save(current, body, at=now, latest=None, run=run_id):
        return prepare_save(
            run_id=run,
            candidate=candidate,
            current=current,
            request=body,
            latest_submission_id=latest,
            saved_at=at,
        )

    first = save(None, request)
    reordered = request.model_copy(
        update={
            "progress": progress.model_copy(
                update={"answers": list(reversed(progress.answers))}
            )
        }
    )
    assert save(first, reordered, datetime(2050, 1, 1, tzinfo=UTC)) is first
    assert first.saved_at == now and first.progress == progress
    other_device = request.model_copy(update={"request_id": uuid.uuid4()})
    with pytest.raises(HTTPException) as conflict:
        save(first, other_device)
    assert conflict.value.status_code == 409
    assert first.progress == progress  # No mutation when a stale device tries to save.
    changed = request.model_copy(update={"progress": DraftProgress(step="coach")})
    with pytest.raises(HTTPException):
        save(first, changed)
    second_request = SaveDraft(
        request_id=uuid.uuid4(),
        expected_version=first.version,
        progress=DraftProgress(step="materials"),
    )
    second = save(first, second_request)
    with pytest.raises(HTTPException):
        save(
            second, request
        )  # An older lost-response retry must not roll back revision 2.
    with pytest.raises(ValueError):
        save(first, second_request, run=uuid.uuid4())
    assert second.run_id == run_id and second.version != first.version
    reused_id = request.model_copy(update={"expected_version": second.version})
    third = save(second, reused_id)
    assert third.version not in {first.version, second.version, request.request_id}
    with pytest.raises(HTTPException):
        save(third, second_request)  # Client IDs cannot restore an old server version.


def test_formal_submission_lineage_conflicts_and_supplement_is_separate(candidate):
    run_id, submission_id = uuid.uuid4(), uuid.uuid4()
    now = datetime.now(UTC)
    request = SaveDraft(
        request_id=uuid.uuid4(), expected_version=None, progress=DraftProgress()
    )
    original = prepare_save(
        run_id=run_id,
        candidate=candidate,
        current=None,
        request=request,
        latest_submission_id=None,
        saved_at=now,
    )
    with pytest.raises(HTTPException) as conflict:
        prepare_save(
            run_id=run_id,
            candidate=candidate,
            current=original,
            request=request,
            latest_submission_id=submission_id,
            saved_at=now,
        )
    assert conflict.value.status_code == 409
    supplement_request = SaveDraft(
        request_id=uuid.uuid4(),
        expected_version=original.version,
        progress=DraftProgress(based_on_submission_id=submission_id),
    )
    supplement = prepare_save(
        run_id=run_id,
        candidate=candidate,
        current=original,
        request=supplement_request,
        latest_submission_id=submission_id,
        saved_at=now,
    )
    assert original.progress.based_on_submission_id is None
    assert supplement.progress.based_on_submission_id == submission_id
    assert set(supplement.model_dump()) == {
        "run_id",
        "version",
        "saved_at",
        "progress",
        "request_id",
    }
