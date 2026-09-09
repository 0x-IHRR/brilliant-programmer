import json
import uuid
from datetime import UTC, datetime

import pytest

from app.training.evaluation_schema import evaluation_inputs
from app.training.independent import (
    Confirmation,
    OrderedDelivery,
    frozen_outcome,
    independence_at_freeze,
    launch_mode,
    publication_permission,
)
from app.training.independent_novelty import assess_novelty
from tests.test_evaluation_schema import example

RUN = uuid.uuid4()
HELP = uuid.uuid4()


def delivery(sequence, status="delivered", direction="directional", **changes):
    return OrderedDelivery(
        id=uuid.uuid4(),
        run_id=RUN,
        help_id=HELP,
        sequence=sequence,
        exposure_sequence=changes.pop("exposure_sequence", sequence),
        occurred_at=datetime.now(UTC),
        status=status,
        direction=direction if status in {"delivered", "partial"} else None,
        delivered_text="实际说明" if status in {"delivered", "partial"} else "",
        content_hash="a" * 64,
        **changes,
    )


def qualification(events, **changes):
    return independence_at_freeze(
        run_id=RUN,
        mode="independent",
        freeze_sequence=10,
        deliveries=events,
        **changes,
    )


def test_entry_defaults_to_practice_and_requires_explicit_new_case():
    original, fresh = uuid.uuid4(), uuid.uuid4()
    assert launch_mode(run_id=original, requested=False, origin_id=None) == "practice"
    assert (
        launch_mode(run_id=fresh, requested=True, origin_id=original) == "independent"
    )
    with pytest.raises(ValueError, match="new round"):
        launch_mode(run_id=original, requested=True, origin_id=original)


@pytest.mark.parametrize("direction", ["directional", "uncertain"])
def test_confirmation_is_bound_to_content_before_publication_and_is_not_delivery(
    direction,
):
    args = {
        "run_id": RUN,
        "help_id": HELP,
        "content_hash": "a" * 64,
        "sequence": 5,
        "mode": "independent",
        "direction": direction,
    }
    permission = publication_permission(**args)
    assert not permission.allowed
    assert "已有修为不变" in permission.prompt
    confirmation = Confirmation(
        run_id=RUN, help_id=HELP, content_hash="a" * 64, sequence=4, direction=direction
    )
    assert publication_permission(**args, confirmation=confirmation).allowed
    for changes in [
        {"help_id": uuid.uuid4()},
        {"run_id": uuid.uuid4()},
        {"content_hash": "b" * 64},
        {"sequence": 5},
    ]:
        assert not publication_permission(
            **args, confirmation=confirmation.model_copy(update=changes)
        ).allowed
    assert qualification([]) == "independent"


def test_neutral_publication_needs_no_conversion_confirmation():
    assert publication_permission(
        run_id=RUN,
        help_id=HELP,
        content_hash="a" * 64,
        sequence=5,
        mode="independent",
        direction="neutral",
    ).allowed
    assert qualification([delivery(2, direction="neutral")]) == "independent"


@pytest.mark.parametrize("status", ["delivered", "partial"])
@pytest.mark.parametrize("direction", ["directional", "uncertain"])
def test_actual_pre_freeze_help_changes_mode_but_post_freeze_does_not(
    status, direction
):
    assert qualification([delivery(9, status, direction)]) == "practice"
    assert qualification([delivery(11, status, direction)]) == "independent"


def test_unknown_waits_and_late_receipt_uses_original_exposure():
    pending = delivery(3, "delivery_unknown")
    assert qualification([pending]) == "pending_delivery"
    receipt = delivery(12, exposure_sequence=3, attempt_id=pending.id)
    assert qualification([pending, receipt]) == "practice"
    assert qualification([receipt, pending]) == "practice"
    assert (
        qualification([pending, receipt.model_copy(update={"direction": "neutral"})])
        == "independent"
    )
    with pytest.raises(ValueError, match="receipt"):
        qualification([pending, receipt.model_copy(update={"content_hash": "b" * 64})])


def test_failed_delivery_and_later_neutral_do_not_invent_or_restore_eligibility():
    assert qualification([delivery(2, "failed")]) == "independent"
    assert qualification([delivery(2, "cancelled")]) == "independent"
    assert qualification([delivery(2), delivery(3, direction="neutral")]) == "practice"
    assert qualification([], converted_sequence=2) == "practice"
    assert qualification([], converted_sequence=12) == "independent"


def outcome_fixture():
    case, sources, original, grade = example()
    return {
        "run_id": original.run_id,
        "mode": "independent",
        "freeze_sequence": 10,
        "case": case,
        "sources": sources,
        "inputs": evaluation_inputs([original]),
        "grading_raw": json.dumps(grade),
        "deliveries": [],
        "key": "fake-key",
        "novelty": assess_novelty(case, sources, {}, [], "fake-key"),
    }, grade


def test_only_frozen_valid_active_novel_independent_pass_produces_candidate():
    args, _ = outcome_fixture()
    assert frozen_outcome(**args) == "independent_pass_candidate"
    assert frozen_outcome(**(args | {"mode": "practice"})) == "practice"
    assert frozen_outcome(**(args | {"converted_sequence": 3})) == "practice"
    assert frozen_outcome(**(args | {"grading_raw": None})) == "system_failure"
    assert (
        frozen_outcome(**(args | {"grading_raw": '{"is_correct":true}'}))
        == "system_failure"
    )
    assert (
        frozen_outcome(
            **(
                args
                | {
                    "novelty": args["novelty"].model_copy(
                        update={"case_digest": "wrong"}
                    )
                }
            )
        )
        == "no_qualified_case"
    )
    with pytest.raises(ValueError, match="freeze"):
        frozen_outcome(**(args | {"freeze_sequence": 1}))


def test_unclear_and_evidenced_failure_are_distinct_and_do_not_grant_pass():
    args, grade = outcome_fixture()
    item = grade["items"][0]
    item["conclusion"] = "unclear"
    item["gap"] = "依据的含义仍不清楚"
    assert frozen_outcome(**(args | {"grading_raw": json.dumps(grade)})) == "unclear"
    item["conclusion"] = "evidenced_fail"
    item["reason_claims"][0]["interpreted_fact_value"] = "true"
    item["gap"] = "原答把未确认解释为已确认"
    assert (
        frozen_outcome(**(args | {"grading_raw": json.dumps(grade)}))
        == "evidenced_fail"
    )


def test_case_failure_is_not_an_ability_failure_and_grading_cannot_escape_secret_gate():
    args, grade = outcome_fixture()
    invalid = args["case"].model_copy(update={"missing_evidence": ["缺少必要处理记录"]})
    assert frozen_outcome(**(args | {"case": invalid})) == "invalid_case"
    grade["items"][0]["explanation"] = "fake-key"
    assert (
        frozen_outcome(**(args | {"grading_raw": json.dumps(grade)}))
        == "system_failure"
    )


def test_permitted_clarification_freeze_uses_later_input_but_neutral_does_not_remove_mode():
    args, grade = outcome_fixture()
    clarification = args["inputs"].original.model_copy(
        update={"id": uuid.uuid4(), "sequence": 4}
    )
    inputs = args["inputs"].model_copy(
        update={"clarification": clarification, "clarification_used": True}
    )
    grade["items"][0]["answer_quotes"].append(
        {
            **grade["items"][0]["answer_quotes"][0],
            "input": "clarification",
        }
    )
    neutral = delivery(3, direction="neutral").model_copy(
        update={"run_id": args["run_id"]}
    )
    before = inputs.model_dump_json()
    assert (
        frozen_outcome(
            **(
                args
                | {
                    "inputs": inputs,
                    "grading_raw": json.dumps(grade),
                    "deliveries": [neutral],
                }
            )
        )
        == "independent_pass_candidate"
    )
    assert inputs.model_dump_json() == before
    with pytest.raises(ValueError, match="freeze"):
        frozen_outcome(
            **(
                args
                | {"inputs": inputs.model_copy(update={"clarification_used": False})}
            )
        )


def test_foreign_duplicate_or_orphan_delivery_facts_are_not_silently_ignored():
    event = delivery(3)
    for events in [
        [event, event],
        [event.model_copy(update={"run_id": uuid.uuid4()})],
        [event.model_copy(update={"attempt_id": uuid.uuid4()})],
    ]:
        with pytest.raises(ValueError):
            qualification(events)
    with pytest.raises(ValueError):
        qualification([delivery(10)])
    with pytest.raises(ValueError):
        qualification([], converted_sequence=10)
