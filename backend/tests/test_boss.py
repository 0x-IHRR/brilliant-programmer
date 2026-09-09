"""Synthetic rule witnesses, not semantic certification of three Boss prompts."""

import copy
import json

import pytest

from app.training.boss import (
    FIRST_STAGE,
    assess_first_boss,
    can_launch_first_boss,
    validate_boss_mapping,
)
from app.training.evaluation_schema import evaluation_inputs
from app.training.independent_novelty import assess_novelty
from app.training.schema import Candidate
from tests.test_evaluation_schema import example
from tests.test_independent import delivery


def facts():
    case, sources, original, grade = example()
    data = case.model_dump()
    data["target"] = FIRST_STAGE.mandatory[0].target.model_dump()
    data["judgments"] = [
        dict(data["judgments"][0], id=m.judgment_id) for m in FIRST_STAGE.mandatory
    ]
    data["rubric"] = [
        dict(data["rubric"][0], judgment_id=m.judgment_id)
        for m in FIRST_STAGE.mandatory
    ]
    case = Candidate.model_validate(data)
    original.answers = [
        dict(original.answers[0], judgment_id=m.judgment_id)
        for m in FIRST_STAGE.mandatory
    ]
    grade["items"] = [
        dict(copy.deepcopy(grade["items"][0]), judgment_id=m.judgment_id)
        for m in FIRST_STAGE.mandatory
    ]
    return {
        "stage": FIRST_STAGE,
        "launch_points": 100,
        "current_level": "小白程序员",
        "run_id": original.run_id,
        "mode": "independent",
        "freeze_sequence": 10,
        "case": case,
        "sources": sources,
        "inputs": evaluation_inputs([original]),
        "grading_raw": json.dumps(grade),
        "novelty": assess_novelty(case, sources, {}, [], "fake-key"),
        "deliveries": [],
        "key": "fake-key",
    }, grade


@pytest.mark.parametrize(
    "points,level,allowed",
    [
        (99, "小白程序员", False),
        (100, "小白程序员", True),
        (9999, "小白程序员", True),
        (9999, "初级程序员", False),
    ],
)
def test_admission_only_uses_stage_points_not_small_level_completions(
    points, level, allowed
):
    assert can_launch_first_boss(points, level) == allowed


@pytest.mark.parametrize("points", [-1, True, 100.5])
def test_invalid_points_are_not_coerced(points):
    with pytest.raises(ValueError):
        can_launch_first_boss(points, "小白程序员")


def test_all_three_independent_pass_once_one_level_no_mutations():
    args, _ = facts()
    before = args["inputs"].model_dump_json()
    result = assess_first_boss(**args)
    assert result.promote_to == "初级程序员" and result.shortfalls == ()
    assert result.semantic_reliability == "unverified"
    assert args["inputs"].model_dump_json() == before
    assert (
        assess_first_boss(**(args | {"current_level": result.promote_to})).promote_to
        is None
    )
    assert assess_first_boss(**(args | {"launch_points": 99})).outcome == "not_admitted"


@pytest.mark.parametrize("field", ["judgments", "rubric"])
def test_every_mandatory_id_is_required_not_just_components_mentioned(field):
    args, _ = facts()
    case = args["case"]
    with pytest.raises(ValueError, match="mapping"):
        validate_boss_mapping(
            FIRST_STAGE, case.model_copy(update={field: getattr(case, field)[:-1]})
        )
    values = list(getattr(case, field))
    values[1] = values[0]
    with pytest.raises(ValueError, match="mapping"):
        validate_boss_mapping(FIRST_STAGE, case.model_copy(update={field: values}))


def test_frozen_stage_cannot_swap_target_background_or_rule():
    args, _ = facts()
    for stage in [
        FIRST_STAGE.model_copy(update={"catalog_version": "other"}),
        FIRST_STAGE.model_copy(update={"passing_rule": "total score is enough"}),
        FIRST_STAGE.model_copy(
            update={"mandatory": tuple(reversed(FIRST_STAGE.mandatory))}
        ),
    ]:
        with pytest.raises(ValueError, match="standard"):
            validate_boss_mapping(stage, args["case"])
    wrong = args["case"].model_copy(update={"target": FIRST_STAGE.mandatory[1].target})
    with pytest.raises(ValueError, match="mapping"):
        validate_boss_mapping(FIRST_STAGE, wrong)


def failed(args, grade):
    item = grade["items"][1]
    item.update(conclusion="evidenced_fail", gap="这项理由与当前冻结事实冲突")
    item["reason_claims"][0]["interpreted_fact_value"] = "true"
    return args | {"grading_raw": json.dumps(grade)}


def test_one_failed_mandatory_cannot_be_offset_and_only_its_target_is_shortfall():
    args, grade = facts()
    result = assess_first_boss(**failed(args, grade))
    assert result.outcome == "evidenced_fail" and result.promote_to is None
    assert len(result.shortfalls) == 1
    assert result.shortfalls[0].target == FIRST_STAGE.mandatory[1].target
    assert result.shortfalls[0].judgment_id == "boss-cause"


@pytest.mark.parametrize(
    "change,expected",
    [
        ({"mode": "practice"}, "practice"),
        ({"disputed": True}, "disputed"),
        ({"grading_raw": None}, "system_failure"),
        ({"converted_sequence": 2}, "practice"),
    ],
)
def test_excluded_outcomes_never_invent_independent_shortfalls(change, expected):
    args, grade = facts()
    result = assess_first_boss(**(failed(args, grade) | change))
    assert (
        result.outcome == expected
        and result.promote_to is None
        and result.shortfalls == ()
    )


def test_invalid_case_unknown_novelty_and_unclear_grade_do_not_fail_user():
    args, grade = facts()
    for change, expected in [
        (
            {
                "case": args["case"].model_copy(
                    update={"conflicts": ["conflicting source"]}
                )
            },
            "invalid_case",
        ),
        (
            {
                "novelty": args["novelty"].model_copy(
                    update={"status": "no_qualified_case"}
                )
            },
            "no_qualified_case",
        ),
    ]:
        result = assess_first_boss(**(args | change))
        assert (
            result.outcome == expected
            and not result.shortfalls
            and result.promote_to is None
        )
    grade["items"][1].update(conclusion="unclear", gap="尚不能确认原答含义")
    result = assess_first_boss(**(args | {"grading_raw": json.dumps(grade)}))
    assert (
        result.outcome == "unclear"
        and result.shortfalls == ()
        and result.promote_to is None
    )


def test_original_exposure_and_late_receipt_preserve_freeze_boundary():
    args, _ = facts()
    unknown = delivery(2, status="delivery_unknown").model_copy(
        update={"run_id": args["run_id"]}
    )
    result = assess_first_boss(**(args | {"deliveries": [unknown]}))
    assert (
        result.outcome == "pending_delivery"
        and not result.shortfalls
        and result.promote_to is None
    )
    receipt = delivery(12, attempt_id=unknown.id, exposure_sequence=2).model_copy(
        update={"run_id": args["run_id"]}
    )
    assert (
        assess_first_boss(**(args | {"deliveries": [unknown, receipt]})).outcome
        == "practice"
    )
    after = delivery(12).model_copy(update={"run_id": args["run_id"]})
    assert (
        assess_first_boss(**(args | {"deliveries": [after]})).promote_to == "初级程序员"
    )
    neutral = delivery(2, direction="neutral").model_copy(
        update={"run_id": args["run_id"]}
    )
    assert (
        assess_first_boss(**(args | {"deliveries": [neutral]})).promote_to
        == "初级程序员"
    )


def test_original_freeze_lineage_and_missing_item_grade_are_checked():
    args, grade = facts()
    with pytest.raises(ValueError, match="freeze"):
        assess_first_boss(**(args | {"freeze_sequence": 1}))
    grade["items"].pop()
    assert (
        assess_first_boss(**(args | {"grading_raw": json.dumps(grade)})).outcome
        == "system_failure"
    )


def test_pending_revalidation_blocks_promotion_not_points_admission():
    args, _ = facts()
    assert can_launch_first_boss(100, "小白程序员")
    result = assess_first_boss(**(args | {"pending_revalidation": True}))
    assert result.outcome == "pending_revalidation" and result.promote_to is None


def test_late_failed_boss_keeps_its_shortfall_after_another_boss_promoted():
    args, grade = facts()
    args = failed(args, grade)
    before = args["inputs"].model_dump_json()
    original_result = assess_first_boss(**args)
    late_result = assess_first_boss(**(args | {"current_level": "初级程序员"}))
    assert original_result.outcome == "evidenced_fail"
    assert len(original_result.shortfalls) == 1
    assert late_result == original_result
    assert args["inputs"].model_dump_json() == before


def test_late_passed_boss_keeps_pass_but_cannot_promote_again():
    args, _ = facts()
    before = args["inputs"].model_dump_json()
    original_result = assess_first_boss(**args)
    late_result = assess_first_boss(**(args | {"current_level": "初级程序员"}))
    assert original_result.promote_to == "初级程序员"
    assert late_result == original_result.model_copy(update={"promote_to": None})
    assert args["inputs"].model_dump_json() == before
