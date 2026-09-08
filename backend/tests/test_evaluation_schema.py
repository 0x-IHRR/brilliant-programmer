"""Controlled grading protocol checks, not a real-model semantic quality score."""

import json
import uuid

import pytest

from app.capabilities.catalog import CATALOG, EvidenceKey
from app.training.evaluation_schema import evaluation_inputs, validate_grading
from app.training.schema import Candidate, Source
from app.training.submission_models import Submission


def example(kind="prediction"):
    source = Source(
        id="reference-1",
        url="https://example.com/controlled-reference",
        version="controlled-v1",
        locator="paragraph 1",
        text="An absent acknowledgement does not prove that the operation did not execute.",
    )
    case = Candidate(
        target=EvidenceKey(
            capability_id="network.delivery",
            difficulty="基础",
            background_id="network-evidence-v1",
        ),
        catalog_version=CATALOG.version,
        title="请求尚未确认",
        task="判断是否有证据断定请求没有执行",
        assumptions=["教学假设：确认可能丢失；没有额外执行记录"],
        evidence=[
            {
                "id": "e1",
                "label": "教学材料",
                "text": "请求尚未收到确认",
                "facts": {"acknowledged": "false"},
                "citations": [{"source_id": source.id, "quote": source.text}],
            }
        ],
        judgments=[
            {
                "id": "judge-delivery",
                "kind": kind,
                "prompt": "可以断定没有执行吗？",
                "options": ["尚不能确定", "先补执行记录", "一定未执行"],
                "evidence_ids": ["e1"],
            }
        ],
        rubric=[
            {
                "judgment_id": "judge-delivery",
                "acceptable_predictions": ["执行状态未知", "需要补充执行记录"]
                if kind == "prediction"
                else [],
                "acceptable_options": [0, 1] if kind == "choice" else [],
                "acceptable_orders": [[0, 1, 2], [1, 0, 2]] if kind == "order" else [],
                "reasoning": "确认缺失不证明请求没有执行；先补执行记录也是有效判断",
                "evidence_ids": ["e1"],
                "counterexample": "请求已执行，但确认丢失",
                "help_boundary": "不得提前指出请求可能已执行",
            }
        ],
        variation={
            "causal_condition": "确认缺失",
            "expected_evidence": "执行记录缺失",
            "decision_effect": "不能确定是否执行",
        },
        missing_evidence=[],
        conflicts=[],
    )
    answer = {
        "judgment_id": "judge-delivery",
        "value": "没回话也许已经做了"
        if kind == "prediction"
        else 0
        if kind == "choice"
        else [0, 1, 2],
        "reason": "对方可能已经办完，只是回话没有传过来",
    }
    original = Submission(
        run_id=uuid.uuid4(),
        config_version=uuid.uuid4(),
        sequence=1,
        answers=[answer],
        input_hash="controlled-original",
        destination="https://provider.example.com/v1",
        model_id="controlled-model",
    )
    result = {
        "items": [
            {
                "judgment_id": "judge-delivery",
                "conclusion": "pass",
                "answer_quotes": [
                    {"input": "original", "field": "reason", "quote": answer["reason"]}
                ],
                "grounding": [
                    {
                        "evidence_id": "e1",
                        "fact": "acknowledged",
                        "value": "false",
                        "citation": {"source_id": source.id, "quote": source.text},
                    }
                ],
                "interpreted_value": "执行状态未知"
                if kind == "prediction"
                else answer["value"],
                "rule_quote": case.rubric[0].reasoning,
                "counterexample_quote": None,
                "explanation": "原答指出了回话丢失这种可能，不能只凭没有确认断定未执行。",
                "gap": None,
            }
        ]
    }
    return case, [source], original, result


@pytest.mark.parametrize("kind", ["choice", "order", "prediction"])
def test_frozen_multiple_valid_solutions_and_plain_language(kind):
    case, sources, original, result = example(kind)
    item = result["items"][0]
    first = validate_grading(
        json.dumps(result), case, sources, evaluation_inputs([original]), "fake-key"
    )
    assert first.items[0].conclusion == "pass" and first.items[0].gap is None
    alternative = (
        1 if kind == "choice" else [1, 0, 2] if kind == "order" else "需要补充执行记录"
    )
    original.answers = [
        {
            **original.answers[0],
            "value": alternative if kind != "prediction" else "先看那边究竟做了没有",
            "reason": "没回话不能定论，得去查执行记录",
        }
    ]
    item["answer_quotes"][0]["quote"] = original.answers[0]["reason"]
    item["interpreted_value"] = alternative
    assert (
        validate_grading(
            json.dumps(result), case, sources, evaluation_inputs([original]), "fake-key"
        )
        .items[0]
        .conclusion
        == "pass"
    )


@pytest.mark.parametrize(
    "fault",
    [
        "missing_item",
        "wrong_judgment",
        "confidence",
        "invented_quote",
        "other_source",
        "other_evidence",
        "invented_fact",
        "other_rule",
        "no_grounding",
        "invented_gap",
        "changed_choice",
        "secret",
        "unsupported_pass",
        "reference_difference_only",
    ],
)
def test_untrusted_verdicts_fail_closed(fault):
    case, sources, original, result = example("choice")
    item = result["items"][0]
    if fault == "missing_item":
        result["items"] = []
    elif fault == "wrong_judgment":
        item["judgment_id"] = "other-task"
    elif fault == "confidence":
        item["confidence"] = 1
    elif fault == "invented_quote":
        item["answer_quotes"][0]["quote"] = "我没说过的话"
    elif fault == "other_source":
        item["grounding"][0]["citation"]["source_id"] = "other-source"
    elif fault == "other_evidence":
        item["grounding"][0]["evidence_id"] = "other-evidence"
    elif fault == "invented_fact":
        item["grounding"][0]["value"] = "true"
    elif fault == "other_rule":
        item["rule_quote"] = "模型自行增加的要求"
    elif fault == "no_grounding":
        item["grounding"] = []
    elif fault == "invented_gap":
        item["gap"] = "没有使用专业术语"
    elif fault == "changed_choice":
        item["interpreted_value"] = 1
    elif fault == "secret":
        item["explanation"] = "fake-key"
    elif fault == "unsupported_pass":
        original.answers[0]["value"] = item["interpreted_value"] = 2
    elif fault == "reference_difference_only":
        original.answers[0]["value"] = item["interpreted_value"] = 2
        item["conclusion"], item["gap"] = "evidenced_fail", "与参考不同"
    with pytest.raises(ValueError):
        validate_grading(
            json.dumps(result), case, sources, evaluation_inputs([original]), "fake-key"
        )


def test_evidenced_failure_and_unresolved_answer_remain_distinct():
    case, sources, original, result = example("choice")
    item = result["items"][0]
    original.answers[0]["value"] = item["interpreted_value"] = 2
    original.answers[0]["reason"] = "没有确认就是一定没执行"
    item["answer_quotes"][0]["quote"] = original.answers[0]["reason"]
    item.update(
        conclusion="evidenced_fail",
        counterexample_quote=case.rubric[0].counterexample,
        gap="原答没有排除已经执行但确认丢失的情况",
    )
    assert (
        validate_grading(
            json.dumps(result), case, sources, evaluation_inputs([original]), "fake-key"
        )
        .items[0]
        .conclusion
        == "evidenced_fail"
    )
    original.answers[0]["reason"] = "也许吧，我不知道这个意思"
    item["answer_quotes"][0]["quote"] = original.answers[0]["reason"]
    item.update(
        conclusion="unclear",
        interpreted_value=None,
        grounding=[],
        rule_quote=None,
        counterexample_quote=None,
        gap="尚不能确定原答认为执行状态是否已知",
    )
    assert (
        validate_grading(
            json.dumps(result), case, sources, evaluation_inputs([original]), "fake-key"
        )
        .items[0]
        .conclusion
        == "unclear"
    )


def test_original_and_one_permitted_clarification_exclude_supplement():
    _, _, original, _ = example()
    original.neutral_clarification = True
    clarification = original.model_copy(
        update={
            "id": uuid.uuid4(),
            "original_id": original.id,
            "kind": "clarification",
            "sequence": 2,
            "neutral_clarification": False,
            "answers": [{**original.answers[0], "reason": "我想表达先补证"}],
        }
    )
    supplement = clarification.model_copy(
        update={
            "id": uuid.uuid4(),
            "kind": "supplement",
            "sequence": 3,
            "answers": [{**original.answers[0], "reason": "看完解析后的新答案"}],
        }
    )
    snapshot = evaluation_inputs([supplement, original, clarification])
    assert snapshot.original.id == original.id
    assert snapshot.clarification.id == clarification.id
    assert snapshot.clarification_used
    assert "看完解析" not in snapshot.model_dump_json()
    # Snapshot does not share a mutable ORM answer dictionary.
    original.answers[0]["reason"] = "another in-memory value"
    assert snapshot.original.answers[0].reason != original.answers[0]["reason"]
    original.neutral_clarification = False
    with pytest.raises(ValueError):
        evaluation_inputs([original, clarification])
    original.neutral_clarification = True
    with pytest.raises(ValueError):
        evaluation_inputs([original, clarification, clarification])
