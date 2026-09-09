import uuid

import pytest

from app.training.independent_novelty import ScenarioComparison, assess_novelty
from app.training.schema import Candidate
from tests import test_guided

frozen = test_guided.frozen


def test_renaming_and_rewording_with_a_new_fingerprint_is_not_novel(frozen):
    case, sources = frozen
    changed = case.model_dump()
    changed["title"] = "服务 B 未收到响应"
    changed["variation"]["causal_condition"] = "响应缺失的新措辞"
    renamed = Candidate.model_validate(changed)
    result = assess_novelty(renamed, sources, {uuid.uuid4(): case}, [], "fake-key")
    assert result.status == "no_qualified_case"
    assert result.reason == "unchanged_judgment_facts"


def test_missing_semantic_comparison_exits_instead_of_trusting_changed_data(frozen):
    case, sources = frozen
    data = case.model_dump()
    data["evidence"][0]["facts"]["ack"] = "present"
    result = assess_novelty(
        Candidate.model_validate(data), sources, {uuid.uuid4(): case}, [], "fake-key"
    )
    assert result.status == "no_qualified_case"
    assert result.reason == "incomplete_comparison"


def variant(case, run_id):
    data = case.model_dump()
    data["evidence"][0]["facts"]["ack"] = "committed_confirmation"
    data["evidence"][0]["text"] = "服务已经返回该事务提交成功的确认。"
    data["judgments"][0]["options"][0] = "保留已完成结果，不重新执行事务"
    data["rubric"][0]["acceptable_options"] = [0]
    data["rubric"][0]["reasoning"] = (
        "事务提交已确认，再执行会重复处理，应保留既有结果。"
    )
    data["variation"] = {
        "causal_condition": "收到事务提交的明确确认",
        "expected_evidence": "已提交记录及确认",
        "decision_effect": "无需再判断是否提交，保留结果",
    }
    new = Candidate.model_validate(data)
    comparison = ScenarioComparison(
        seen_run_id=run_id,
        seen_judgment_id="j1",
        new_judgment_id="j1",
        relation="different_causal_scenario",
        changes=[
            {
                "dimension": "causal_condition",
                "before": {"evidence_id": "e1", "fact": "ack", "value": "absent"},
                "after": {
                    "evidence_id": "e1",
                    "fact": "ack",
                    "value": "committed_confirmation",
                },
                "before_variation": case.variation.causal_condition,
                "after_variation": new.variation.causal_condition,
                "before_reasoning": case.rubric[0].reasoning,
                "after_reasoning": new.rubric[0].reasoning,
                "before_consequence": case.judgments[0].options[0],
                "after_consequence": new.judgments[0].options[0],
                "effect": "different_decision",
                "explanation": "原题缺确认，执行状态仍不明；新题明确已提交，重新执行会重复处理。",
            }
        ],
    )
    return new, comparison


def test_structurally_similar_but_causally_different_case_is_a_candidate(frozen):
    case, sources = frozen
    run_id = uuid.uuid4()
    new, comparison = variant(case, run_id)
    result = assess_novelty(new, sources, {run_id: case}, [comparison], "fake-key")
    assert result.status == "novelty_candidate"
    assert result.semantic_reliability == "unverified"
    assert new.judgments[0].kind == case.judgments[0].kind
    assert new.judgments[0].id == case.judgments[0].id


@pytest.mark.parametrize(
    "field,value",
    [
        ("before_consequence", "随便一个不同字符串"),
        ("after_consequence", "另一个不同字符串"),
        ("before_reasoning", "模型自称有根据"),
        ("after_variation", "未绑定的变化"),
        (
            "after",
            {
                "evidence_id": "missing",
                "fact": "ack",
                "value": "committed_confirmation",
            },
        ),
    ],
)
def test_model_claim_must_bind_actual_facts_rules_and_decisions(frozen, field, value):
    case, sources = frozen
    run_id = uuid.uuid4()
    new, comparison = variant(case, run_id)
    data = comparison.model_dump()
    data["changes"][0][field] = value
    result = assess_novelty(
        new,
        sources,
        {run_id: case},
        [ScenarioComparison.model_validate(data)],
        "fake-key",
    )
    assert result.status == "no_qualified_case"
    assert result.reason == "unbound_or_cosmetic_change"


@pytest.mark.parametrize("relation", ["same_scenario", "unclear"])
def test_paraphrase_or_unknown_semantics_exit_despite_complete_structure(
    frozen, relation
):
    case, sources = frozen
    run_id = uuid.uuid4()
    new, comparison = variant(case, run_id)
    comparison = comparison.model_copy(update={"relation": relation})
    assert (
        assess_novelty(new, sources, {run_id: case}, [comparison], "fake-key").status
        == "no_qualified_case"
    )


def test_comparison_cannot_omit_another_seen_session_or_duplicate_a_pair(frozen):
    case, sources = frozen
    run_id, another_id = uuid.uuid4(), uuid.uuid4()
    new, comparison = variant(case, run_id)
    assert (
        assess_novelty(
            new, sources, {run_id: case, another_id: case}, [comparison], "fake-key"
        ).reason
        == "incomplete_comparison"
    )
    assert (
        assess_novelty(
            new, sources, {run_id: case}, [comparison, comparison], "fake-key"
        ).reason
        == "incomplete_comparison"
    )


def test_new_case_incomplete_sources_and_encoded_secret_are_rejected(frozen):
    case, sources = frozen
    run_id = uuid.uuid4()
    new, comparison = variant(case, run_id)
    with pytest.raises(ValueError):
        assess_novelty(new, [], {run_id: case}, [comparison], "fake-key")
    data = comparison.model_dump()
    data["changes"][0]["explanation"] = "fake-key"
    with pytest.raises(ValueError):
        assess_novelty(
            new,
            sources,
            {run_id: case},
            [ScenarioComparison.model_validate(data)],
            "fake-key",
        )


def test_same_decision_with_different_required_evidence_can_be_a_variant(frozen):
    case, sources = frozen
    run_id = uuid.uuid4()
    new, comparison = variant(case, run_id)
    data = new.model_dump()
    data["judgments"] = [j.model_dump() for j in case.judgments]
    data["rubric"][0]["acceptable_options"] = case.rubric[0].acceptable_options
    data["evidence"][0]["facts"]["ack"] = "received_but_not_committed"
    data["evidence"][0]["text"] = "收件确认已返回，但没有事务提交记录。"
    data["variation"]["causal_condition"] = "收件确认不代表提交确认"
    data["variation"]["expected_evidence"] = "事务提交记录"
    data["rubric"][0]["reasoning"] = "收件已知，提交仍不明，需要查事务提交记录再判断。"
    new = Candidate.model_validate(data)
    record = comparison.model_dump()
    change = record["changes"][0]
    change.update(
        {
            "effect": "different_required_evidence",
            "dimension": "expected_evidence",
            "after": {
                "evidence_id": "e1",
                "fact": "ack",
                "value": "received_but_not_committed",
            },
            "before_variation": case.variation.expected_evidence,
            "after_variation": new.variation.expected_evidence,
            "before_consequence": case.variation.expected_evidence,
            "after_consequence": new.variation.expected_evidence,
            "after_reasoning": new.rubric[0].reasoning,
            "explanation": "原题需查处理状态；新题已确认接收，需要进一步区分事务是否提交。",
        }
    )
    assert (
        assess_novelty(
            new,
            sources,
            {run_id: case},
            [ScenarioComparison.model_validate(record)],
            "fake-key",
        ).status
        == "novelty_candidate"
    )


def test_reworded_same_scenario_does_not_gain_novelty_from_different_option_text(
    frozen,
):
    case, sources = frozen
    run_id = uuid.uuid4()
    data = case.model_dump()
    data["judgments"][0]["options"][0] = "先查处理日志"
    data["rubric"][0]["reasoning"] = "没收到确认并不说明未处理，要先查日志。"
    data["variation"]["causal_condition"] = "响应确认缺失"
    new = Candidate.model_validate(data)
    _, comparison = variant(case, run_id)
    record = comparison.model_dump()
    record["changes"][0].update(
        {
            "after": {"evidence_id": "e1", "fact": "ack", "value": "absent"},
            "after_consequence": new.judgments[0].options[0],
            "after_reasoning": new.rubric[0].reasoning,
            "after_variation": new.variation.causal_condition,
        }
    )
    assert (
        assess_novelty(
            new,
            sources,
            {run_id: case},
            [ScenarioComparison.model_validate(record)],
            "fake-key",
        ).status
        == "no_qualified_case"
    )
