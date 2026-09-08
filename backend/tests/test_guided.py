import json

import pytest

from app.capabilities.catalog import CATALOG, EvidenceKey
from app.training.guided import (
    exercise_candidate,
    guidance_draft,
    practice_case,
    practice_completion,
)
from app.training.schema import Candidate, Source, scenario_fingerprint
from app.training.submission_schema import Answer, Relevance


@pytest.fixture
def frozen():
    source = Source(
        id="s1",
        url="https://example.com/reference",
        version="frozen-v1",
        locator="paragraph 1",
        text="Missing acknowledgement does not prove that an operation was not executed.",
    )
    value = {
        "target": EvidenceKey(
            capability_id="network.delivery",
            difficulty="基础",
            background_id="network-evidence-v1",
        ).model_dump(),
        "catalog_version": CATALOG.version,
        "title": "请求没有确认",
        "task": "选择下一步并说明理由。",
        "assumptions": ["合成教学案例"],
        "evidence": [
            {
                "id": "e1",
                "label": "教学材料",
                "text": "请求没有收到确认。",
                "facts": {"ack": "absent"},
                "citations": [{"source_id": "s1", "quote": source.text}],
            }
        ],
        "judgments": [
            {
                "id": "j1",
                "kind": "choice",
                "prompt": "下一步？",
                "options": [
                    "先核对处理记录",
                    "直接认定没有执行",
                    "先确认重复请求是否安全",
                ],
                "evidence_ids": ["e1"],
            }
        ],
        "rubric": [
            {
                "judgment_id": "j1",
                "acceptable_options": [0, 2],
                "reasoning": "未确认不代表未执行，先核对处理证据或重试安全性。",
                "evidence_ids": ["e1"],
                "counterexample": "服务可能执行后丢失了确认。",
                "help_boundary": "PRIVATE_HELP_BOUNDARY",
            }
        ],
        "variation": {
            "causal_condition": "确认丢失",
            "expected_evidence": "处理记录",
            "decision_effect": "先核对再决定是否重试",
        },
        "missing_evidence": [],
        "conflicts": [],
    }
    return Candidate.model_validate(value), [source]


def test_hint_does_not_include_frozen_solution_or_private_metadata(frozen):
    case, sources = frozen
    hint = guidance_draft(case, sources, "hint", "fake-key")
    encoded = hint.model_dump_json()
    assert hint.direction == "directional"
    assert hint.steps[0].evidence[0].citations == case.evidence[0].citations
    assert hint.steps[0].solution is None
    assert case.rubric[0].reasoning not in encoded
    assert case.rubric[0].counterexample not in encoded
    assert "PRIVATE_HELP_BOUNDARY" not in encoded


@pytest.mark.parametrize("kind", ["choice", "order", "prediction"])
def test_demonstration_keeps_all_frozen_alternatives_and_evidence(frozen, kind):
    case, sources = frozen
    data = case.model_dump()
    data["judgments"][0]["kind"] = kind
    rule = data["rubric"][0]
    rule["acceptable_options"] = [0, 2] if kind == "choice" else []
    rule["acceptable_orders"] = [[0, 1, 2], [2, 0, 1]] if kind == "order" else []
    rule["acceptable_predictions"] = (
        ["无法确定", "需要处理记录"] if kind == "prediction" else []
    )
    case = Candidate.model_validate(data)
    before = case.model_dump_json()
    draft = guidance_draft(case, sources, "demonstration", "fake-key")
    step = draft.steps[0]
    assert step.solution.acceptable_values == (
        rule["acceptable_options"]
        + rule["acceptable_orders"]
        + rule["acceptable_predictions"]
    )
    assert step.solution.reasoning == rule["reasoning"]
    assert step.solution.counterexample == rule["counterexample"]
    assert draft.scenario_fingerprint == scenario_fingerprint(case)
    assert case.model_dump_json() == before


def test_small_exercise_keeps_seen_scenario_but_not_answers_or_original_mutation(
    frozen,
):
    case, sources = frozen
    data = case.model_dump()
    data["judgments"].append({**data["judgments"][0], "id": "j2"})
    data["rubric"].append({**data["rubric"][0], "judgment_id": "j2"})
    case = Candidate.model_validate(data)
    before = case.model_dump_json()
    practice = practice_case(case, sources, "j2", "fake-key")
    assert practice.kind == "same_scenario_practice"
    assert practice.scenario_fingerprint == scenario_fingerprint(case)
    assert [j.id for j in practice.case.judgments] == ["j2"]
    encoded = practice.model_dump_json()
    for private in [
        "acceptable_options",
        "rubric",
        "PRIVATE_HELP_BOUNDARY",
        case.rubric[0].reasoning,
        '"answers"',
    ]:
        assert private not in encoded
    exercise = exercise_candidate(case, "j2")
    result = practice_completion(
        exercise,
        [Answer(judgment_id="j2", value=1, reason="我不知道原因，想先查处理记录。")],
        Relevance.model_validate(
            {"items": [{"judgment_id": "j2", "status": "related"}]}
        ),
    )
    assert (
        result == "completed"
    )  # Wrong option, plain relevant reason, no correctness gate.
    assert case.model_dump_json() == before


@pytest.mark.parametrize(
    "fault",
    [
        "missing_answer",
        "blank_reason",
        "wrong_id",
        "duplicate_relevance",
        "missing_relevance",
        "wrong_relevance_id",
        "invalid_choice",
    ],
)
def test_incomplete_or_forged_practice_cannot_complete(frozen, fault):
    case, _ = frozen
    answers = [{"judgment_id": "j1", "value": 1, "reason": "想核对记录"}]
    items = [{"judgment_id": "j1", "status": "related"}]
    if fault == "missing_answer":
        answers = []
    if fault == "blank_reason":
        answers[0]["reason"] = " "
    if fault == "wrong_id":
        answers[0]["judgment_id"] = "foreign"
    if fault == "duplicate_relevance":
        items *= 2
    if fault == "missing_relevance":
        items = []
    if fault == "wrong_relevance_id":
        items[0]["judgment_id"] = "foreign"
    if fault == "invalid_choice":
        answers[0]["value"] = 99
    with pytest.raises(ValueError):
        practice_completion(
            case,
            [Answer.model_validate(a) for a in answers],
            Relevance.model_validate({"items": items}),
        )


@pytest.mark.parametrize("status", ["unrelated", "unclear"])
def test_unresolved_relevance_is_not_failure_or_completion(frozen, status):
    case, _ = frozen
    result = practice_completion(
        case,
        [Answer(judgment_id="j1", value=1, reason="这是我的理由")],
        Relevance.model_validate({"items": [{"judgment_id": "j1", "status": status}]}),
    )
    assert result == "needs_supplement"


@pytest.mark.parametrize(
    "fault",
    ["secret", "encoded_secret", "bad_source", "foreign_judgment", "extra_instruction"],
)
def test_existing_case_and_secret_gates_remain_at_boundary(frozen, fault):
    case, sources = frozen
    data = case.model_dump()
    if fault in {"secret", "encoded_secret"}:
        data["rubric"][0]["reasoning"] = "synthetic-private-key"
    if fault == "bad_source":
        data["evidence"][0]["citations"][0]["quote"] = (
            "This is an invented unsupported reference quotation."
        )
    if fault == "extra_instruction":
        data["execute_tool"] = "publish_answers"
    with pytest.raises(ValueError):
        raw = json.dumps(data)
        if fault == "encoded_secret":
            raw = raw.replace(
                "synthetic-private-key",
                "".join(f"\\u{ord(c):04x}" for c in "synthetic-private-key"),
            )
        case = Candidate.model_validate_json(raw)
        if fault == "foreign_judgment":
            practice_case(case, sources, "missing", "synthetic-private-key")
        else:
            guidance_draft(case, sources, "demonstration", "synthetic-private-key")
