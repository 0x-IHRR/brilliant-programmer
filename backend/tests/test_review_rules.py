"""Controlled review witnesses and history replay; no DB/model-quality claim."""

import copy
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.capabilities.evidence import Evidence
from app.training.evaluation_schema import GradingCandidate, evaluation_inputs
from app.training.review_rules import (
    accept,
    conclude,
    freeze,
    recalculate,
    reward_difference,
)
from app.training.submission_models import REWARD_RULE
from tests.test_evaluation_schema import example


def fixture():
    case, sources, original, grading = example()
    old = copy.deepcopy(grading)
    old["items"][0]["conclusion"] = "unclear"
    old["items"][0]["gap"] = "原判没有确认这段表达的含义"
    frozen = freeze(
        original.run_id,
        2,
        3,
        "evidence-feedback-v1.0",
        case,
        sources,
        evaluation_inputs([original]),
        GradingCandidate.model_validate(old),
    )
    return accept(uuid.uuid4(), frozen, None), grading


def opinion(grading, decision="corrected"):
    return json.dumps(
        {
            "decision": decision,
            "explanation": "原答和冻结材料支持同一判断，核对引用及推理。",
            "grading": grading,
        }
    )


def evidence(review, order=None, **changes):
    case, _, _, _ = example()
    position = order or review.snapshot.original_order
    return Evidence(
        original_id=review.snapshot.original_id if order is None else uuid.uuid4(),
        run_id=review.snapshot.run_id if order is None else uuid.uuid4(),
        order=position,
        submitted_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=position),
        order_source="user_locked",
        target=case.target,
        observation_id=uuid.uuid4(),
        observation_sequence=4,
        frozen_sequence=3,
        outcome=changes.pop("outcome", "independent_pass_candidate"),
        qualified_novelty=changes.pop("qualified_novelty", True),
        case_digest=f"controlled-distinct-{position}",
        judgment_ids=["judge-delivery"],
        **changes,
    )


def test_once_accepted_and_snapshot_cannot_follow_later_edits():
    review, _ = fixture()
    assert accept(review.request_id, review.snapshot, review) is review
    with pytest.raises(ValueError):
        accept(uuid.uuid4(), review.snapshot, review)
    changed = review.snapshot.model_copy(update={"sources_json": "[]"})
    with pytest.raises(ValueError):
        accept(review.request_id, changed, review)
    with pytest.raises(ValueError):
        review.snapshot.original_order = 7
    source = json.loads(review.snapshot.sources_json)
    source[0]["text"] = "new source"
    assert "new source" not in review.snapshot.sources_json


def test_witnessed_correction_and_idempotent_terminal_no_late_overwrite():
    review, grading = fixture()
    result = conclude(review, opinion(grading), "")
    assert result.status == "corrected"
    assert result.snapshot == review.snapshot
    assert conclude(result, opinion(grading), "") is result
    with pytest.raises(ValueError):
        conclude(result, opinion(None, "disputed"), "")
    assert review.status == "pending"  # transport failure has no terminal mutation


def test_upheld_requires_same_actual_conclusions_and_witnesses():
    review, grading = fixture()
    review = review.model_copy(
        update={
            "snapshot": review.snapshot.model_copy(
                update={"grading_json": json.dumps(grading)}
            )
        }
    )
    assert conclude(review, opinion(grading, "upheld"), "").status == "upheld"
    with pytest.raises(ValueError):
        conclude(review, opinion(grading, "corrected"), "")
    grading["items"][0]["grounding"] = []
    with pytest.raises(ValueError):
        conclude(review, opinion(grading, "upheld"), "")


@pytest.mark.parametrize(
    "tamper", ["answer", "source", "rule", "bare", "confidence", "secret"]
)
def test_reject_post_answer_new_source_different_rule_and_bare_confidence(tamper):
    review, grading = fixture()
    item = grading["items"][0]
    if tamper == "answer":
        item["answer_quotes"][0]["quote"] = "看过解析后重新作答"
    elif tamper == "source":
        item["grounding"][0]["citation"]["source_id"] = "new-reference"
    elif tamper == "rule":
        item["rule_quote"] = "事后新假设改变判据"
    elif tamper == "bare":
        item["reason_claims"] = []
    raw = json.loads(opinion(grading))
    if tamper == "confidence":
        raw["confidence"] = 1
    if tamper == "secret":
        raw["explanation"] = "test-secret-value"
    with pytest.raises(ValueError):
        conclude(
            review, json.dumps(raw), "test-secret-value" if tamper == "secret" else ""
        )


def test_uncertain_opinion_stays_disputed_without_installing_grading():
    review, _ = fixture()
    old = json.loads(review.snapshot.grading_json)
    with pytest.raises(ValueError):
        conclude(review, opinion(old, "upheld"), "")
    result = conclude(review, opinion(None, "disputed"), "")
    assert result.status == "disputed"
    with pytest.raises(ValueError):
        conclude(review, opinion(old, "disputed"), "")


def test_pending_replays_current_history_and_correction_stays_original_order():
    review, grading = fixture()
    first, old, later = (
        evidence(review, 1),
        evidence(review, outcome="evidenced_fail"),
        evidence(review, 3),
    )
    records = [later, old, first]
    saved = [r.model_dump() for r in records]
    pending = recalculate(records, [review]).states[0]
    assert pending.streak == 2 and pending.status == "verified"
    assert [h.evidence.order for h in pending.history] == [1, 2, 3]
    assert not pending.history[1].counted
    corrected = recalculate(records, [conclude(review, opinion(grading), "")]).states[0]
    assert corrected.streak == 3
    assert corrected.latest_verified_at == later.submitted_at
    assert [r.model_dump() for r in records] == saved


def test_pending_pass_removes_existing_proof_without_calling_it_failure():
    review, _ = fixture()
    records = [evidence(review, 1), evidence(review)]
    assert recalculate(records, []).states[0].status == "verified"
    pending = recalculate(records, [review]).states[0]
    assert pending.status == "unverified" and pending.streak == 1
    disputed = conclude(review, opinion(None, "disputed"), "")
    assert recalculate(records, [disputed]).states[0].streak == 1


def test_wrong_identity_duplicates_and_cross_background_never_merge():
    review, grading = fixture()
    record = evidence(review)
    for field, value in [
        ("order", 9),
        ("run_id", uuid.uuid4()),
        ("frozen_sequence", 8),
    ]:
        with pytest.raises(ValueError):
            recalculate([record.model_copy(update={field: value})], [review])
    with pytest.raises(ValueError):
        recalculate([record], [review, review])
    other = evidence(review, 3).model_copy(
        update={
            "target": record.target.model_copy(
                update={"background_id": "other-background"}
            )
        }
    )
    result = recalculate([other, record], [conclude(review, opinion(grading), "")])
    assert len(result.states) == 2 and all(s.streak == 1 for s in result.states)
    with pytest.raises(ValueError):
        recalculate([record.model_copy(update={"target": other.target})], [review])


@pytest.mark.parametrize(
    "paid,completed,expected",
    [(0, True, 10), (4, True, 6), (10, True, 0), (14, True, 0), (0, False, 0)],
)
def test_only_original_round_difference_including_previous_supplements(
    paid, completed, expected
):
    review, grading = fixture()
    result = conclude(review, opinion(grading), "")
    assert (
        reward_difference(review, completed=True, rule_version=REWARD_RULE, paid=paid)
        == 0
    )
    delta = reward_difference(
        result, completed=completed, rule_version=REWARD_RULE, paid=paid
    )
    assert delta == expected
    assert (
        reward_difference(
            result, completed=completed, rule_version=REWARD_RULE, paid=paid + delta
        )
        == 0
    )
    with pytest.raises(ValueError):
        reward_difference(result, completed=True, rule_version="future-rule", paid=paid)


def test_original_evaluation_permitted_clarification_is_retained_and_required():
    from app.training.evaluation_schema import EvaluationInputs

    review, grading = fixture()
    inputs = EvaluationInputs.model_validate_json(review.snapshot.inputs_json)
    clarification = inputs.original.model_copy(
        update={"id": uuid.uuid4(), "sequence": 2}
    )
    inputs = inputs.model_copy(
        update={"clarification": clarification, "clarification_used": True}
    )
    review = review.model_copy(
        update={
            "snapshot": review.snapshot.model_copy(
                update={"inputs_json": inputs.model_dump_json()}
            )
        }
    )
    with pytest.raises(ValueError):
        conclude(review, opinion(grading), "")
    grading["items"][0]["answer_quotes"].append(
        {
            "input": "clarification",
            "field": "reason",
            "quote": clarification.answers[0].reason,
        }
    )
    assert conclude(review, opinion(grading), "").status == "corrected"
    grading["items"][0]["answer_quotes"][-1]["quote"] = "事后看解析才有的改答"
    with pytest.raises(ValueError):
        conclude(review, opinion(grading), "")


def test_corrected_failure_replays_at_original_position_without_erasing_later_pass():
    review, grading = fixture()
    review = review.model_copy(
        update={
            "snapshot": review.snapshot.model_copy(
                update={"grading_json": json.dumps(grading)}
            )
        }
    )
    item = grading["items"][0]
    item["conclusion"] = "evidenced_fail"
    item["reason_claims"][0]["interpreted_fact_value"] = "true"
    item["gap"] = "本受控复核将原答解释为有确认，与冻结事实相反；真实解释质量须另验"
    corrected = conclude(review, opinion(grading), "")
    records = [evidence(review, 3), evidence(review), evidence(review, 1)]
    projected = recalculate(records, [corrected]).states[0]
    assert projected.streak == 1 and projected.status == "unverified"
    assert [h.evidence.order for h in projected.history] == [1, 2, 3]
    assert projected.history[1].evidence.outcome == "evidenced_fail"
    ordinary = evidence(review, qualified_novelty=False, outcome="practice")
    assert not recalculate([ordinary], [corrected]).states[0].history[0].counted
