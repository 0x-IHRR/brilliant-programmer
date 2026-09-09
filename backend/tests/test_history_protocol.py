"""Fixed-reference wire and completeness tests; no worker/DB/model invocation."""

import json
import uuid

import pytest

from app.training.history_protocol import (
    REQUEST_BYTES,
    RESPONSE_BYTES,
    SNAPSHOT_BYTES,
    CapacityError,
    HistorySnapshot,
    ReferenceResponse,
    assess_plan,
    context,
    decode_batch,
    freeze_history,
    load_history,
    plan_comparison,
    restore_history,
    wire_request,
)
from tests.test_boss_history_size import fixture


def response_for(batch, full):
    """Encode pre-existing explicit semantic witnesses, never infer from IDs."""
    by_pair = {(c.seen_run_id, c.seen_judgment_id, c.new_judgment_id): c for c in full}
    changes, explanations, rows = [], [], []
    exact = {}
    for index, (run_index, old_j, new_j) in enumerate(batch.pairs):
        run = batch.runs[run_index]
        old = batch.seen[run.case]
        comparison = by_pair[
            run.run_id, old.judgments[old_j].id, batch.new.judgments[new_j].id
        ]
        refs = []
        for change in comparison.changes:
            if change.explanation not in explanations:
                explanations.append(change.explanation)
            before = next(
                i
                for i, r in enumerate(old.rubric)
                if r.judgment_id == comparison.seen_judgment_id
            )
            after = next(
                i
                for i, r in enumerate(batch.new.rubric)
                if r.judgment_id == comparison.new_judgment_id
            )
            row = {
                "c": run.case,
                "r": before,
                "n": after,
                "b": old.facts.index(change.before),
                "a": batch.new.facts.index(change.after),
                "d": {
                    "causal_condition": "cause",
                    "expected_evidence": "evidence",
                    "decision_effect": "decision",
                }[change.dimension],
                "e": "decision"
                if change.effect == "different_decision"
                else "evidence",
                "bc": old.rubric[before].consequences.index(change.before_consequence)
                if change.effect == "different_decision"
                else 0,
                "ac": batch.new.rubric[after].consequences.index(
                    change.after_consequence
                )
                if change.effect == "different_decision"
                else 0,
                "x": explanations.index(change.explanation),
            }
            literal = json.dumps(row, sort_keys=True)
            if literal not in exact:
                exact[literal] = len(changes)
                changes.append(row)
            refs.append(exact[literal])
        rows.append(
            [
                index,
                {
                    "same_scenario": "same",
                    "different_causal_scenario": "different",
                    "unclear": "unclear",
                }[comparison.relation],
                refs,
            ]
        )
    return json.dumps(
        {
            "version": "comparison-references-v1",
            "plan_id": batch.plan_id,
            "batch": batch.batch,
            "explanations": explanations,
            "changes": changes,
            "comparisons": rows,
            "coverage": [],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def prepared(count=4, width=3, **kwargs):
    history, new, sources, full = fixture(count, width)
    plan = plan_comparison(
        freeze_history(history), new, sources, "controlled-model", "fake-key", **kwargs
    )
    return plan, new, sources, full


def test_snapshot_exact_roundtrip_keeps_every_run_and_private_fields_server_side():
    history, new, sources, _ = fixture(3, 1)
    history[uuid.UUID(int=4)] = next(iter(history.values()))
    snapshot = freeze_history(history)
    assert len(snapshot.runs) == 4 and len(snapshot.cases) == 3
    assert restore_history(load_history(snapshot.model_dump_json())) == history
    assert "PRIVATE_HELP_BOUNDARY" in snapshot.model_dump_json()
    plan = plan_comparison(snapshot, new, sources, "controlled-model", "fake-key")
    wire = wire_request(plan.batches[0], plan.model_id)
    assert b"PRIVATE_HELP_BOUNDARY" not in wire
    assert b"counterexample" not in wire
    body = json.loads(json.loads(wire)["messages"][1]["content"])
    assert body["input"]["sources"] == [s.model_dump(mode="json") for s in sources]
    assert body["schema"] == ReferenceResponse.model_json_schema()
    assert body["input"]["new"] == context(new, new_case=True).model_dump(mode="json")
    assert sum(len(b.pairs) for b in plan.batches) == 16


@pytest.mark.parametrize("fault", ["negative", "bool", "range", "duplicate", "orphan"])
def test_snapshot_rejects_invalid_references(fault):
    history, _, _, _ = fixture(2, 1)
    data = freeze_history(history).model_dump(mode="json")
    if fault in {"negative", "bool", "range"}:
        data["runs"][0]["case"] = {"negative": -1, "bool": True, "range": 2}[fault]
    elif fault == "duplicate":
        data["runs"].append(data["runs"][0])
    else:
        data["runs"].pop()
    with pytest.raises(ValueError):
        load_history(json.dumps(data))


def test_snapshot_size_is_independent_of_wire_size_and_checked_before_parse():
    with pytest.raises(CapacityError, match="snapshot"):
        load_history("x" * (SNAPSHOT_BYTES + 1))
    history, new, sources, _ = fixture(2, 1)
    case = next(iter(history.values()))
    # A legal shape can still contain oversized arbitrary fact text; fail the
    # complete request unit rather than silently dropping the material.
    data = case.model_dump()
    data["evidence"][0]["facts"] = {f"fact-{i}": "z" * 6000 for i in range(30)}
    data["evidence"] = [dict(data["evidence"][0], id=f"e{i}") for i in range(1, 13)]
    history = {uuid.UUID(int=1): type(case).model_validate(data)}
    snapshot = freeze_history(history)
    assert len(snapshot.model_dump_json().encode()) < SNAPSHOT_BYTES
    with pytest.raises(CapacityError, match="single_comparison_unit"):
        plan_comparison(snapshot, new, sources, "controlled-model", "fake-key")


def test_deterministic_partition_measures_real_wire_and_never_returns_partial_plan():
    plan, new, sources, _ = prepared(count=30, width=3)
    full_size = len(wire_request(plan.batches[0], plan.model_id))
    # Limit deliberately forces more than one complete wire request, including
    # repeated schema/new/source overhead. It is not a history-only estimate.
    limit = full_size * 3 // 5
    split = plan_comparison(
        plan.snapshot, new, sources, plan.model_id, "fake-key", request_limit=limit
    )
    assert 1 < len(split.batches) <= 3
    assert all(len(wire_request(b, split.model_id)) <= limit for b in split.batches)
    assert sum(len(b.pairs) for b in split.batches) == 30 * 3 * 4
    assert split == plan_comparison(
        plan.snapshot, new, sources, plan.model_id, "fake-key", request_limit=limit
    )
    with pytest.raises(CapacityError, match="remaining_comparison_calls"):
        plan_comparison(
            plan.snapshot,
            new,
            sources,
            plan.model_id,
            "fake-key",
            request_limit=limit,
            remaining_calls=1,
        )
    with pytest.raises(CapacityError, match="single_comparison_unit"):
        plan_comparison(
            plan.snapshot, new, sources, plan.model_id, "fake-key", request_limit=100
        )


@pytest.mark.parametrize("calls", [0, 4, True])
def test_no_fresh_comparison_budget_can_be_invented(calls):
    with pytest.raises(CapacityError):
        prepared(remaining_calls=calls)


def test_all_600_rounds_and_7200_actual_pairs_use_bounded_requests_and_responses():
    plan, new, sources, full = prepared(600, 3)
    responses = [response_for(batch, full) for batch in plan.batches]
    assert len(plan.snapshot.runs) == 600 and len(plan.snapshot.cases) == 600
    assert sum(len(b.pairs) for b in plan.batches) == 7200
    assert len(plan.batches) <= 3
    assert all(
        len(wire_request(b, plan.model_id)) <= REQUEST_BYTES for b in plan.batches
    )
    assert all(len(r.encode()) <= RESPONSE_BYTES for r in responses)
    decoded = [
        c
        for b, r in zip(plan.batches, responses, strict=True)
        for c in decode_batch(r, b, "fake-key")
    ]
    assert {c.model_dump_json() for c in decoded} == {c.model_dump_json() for c in full}
    result = assess_plan(plan, new, sources, responses, "fake-key")
    assert (
        result.status == "novelty_candidate"
        and result.semantic_reliability == "unverified"
    )
    with pytest.raises(ValueError, match="incomplete comparison batches"):
        assess_plan(plan, new, sources, responses[:-1], "fake-key")


@pytest.mark.parametrize(
    "fault",
    [
        "pair_missing",
        "pair_duplicate",
        "pair_extra",
        "negative",
        "bool",
        "fact_range",
        "rule_range",
        "wrong_case",
        "wrong_judgment",
        "unused_change",
        "explanation_range",
        "unused_explanation",
        "wrong_plan",
        "wrong_batch",
    ],
)
def test_untrusted_response_references_fail_closed(fault):
    plan, _, _, full = prepared()
    batch = plan.batches[0]
    data = json.loads(response_for(batch, full))
    if fault == "pair_missing":
        data["comparisons"].pop()
    elif fault == "pair_duplicate":
        data["comparisons"][-1] = data["comparisons"][0]
    elif fault == "pair_extra":
        data["comparisons"].append([99999, "unclear", []])
    elif fault == "negative":
        data["changes"][0]["b"] = -1
    elif fault == "bool":
        data["changes"][0]["b"] = True
    elif fault == "fact_range":
        data["changes"][0]["b"] = 99999
    elif fault == "rule_range":
        data["changes"][0]["r"] = 99999
    elif fault == "wrong_case":
        data["changes"][0]["c"] = 1
    elif fault == "wrong_judgment":
        data["changes"][0]["n"] = 1
    elif fault == "unused_change":
        data["changes"].append(data["changes"][0])
    elif fault == "explanation_range":
        data["changes"][0]["x"] = 99
    elif fault == "unused_explanation":
        data["explanations"].append("额外无关说明")
    elif fault == "wrong_plan":
        data["plan_id"] = "another-plan"
    elif fault == "wrong_batch":
        data["batch"] = 2
    with pytest.raises(ValueError):
        decode_batch(json.dumps(data), batch, "fake-key")


def test_unknown_and_cosmetic_claims_remain_ineligible_after_expansion():
    plan, new, sources, full = prepared()
    data = json.loads(response_for(plan.batches[0], full))
    data["comparisons"][0][1] = "unclear"
    result = assess_plan(plan, new, sources, [json.dumps(data)], "fake-key")
    assert result.status == "no_qualified_case" and result.reason == "unclear"
    # Valid references do not authorize a made-up relationship. Pick an unchanged
    # fact value while keeping the model's different-decision claim.
    old = next(iter(restore_history(plan.snapshot).values()))
    changed = new.model_dump()
    changed["evidence"][0]["facts"]["ack"] = "absent"
    altered = type(new).model_validate(changed)
    altered_plan = plan_comparison(
        plan.snapshot, altered, sources, plan.model_id, "fake-key"
    )
    data = json.loads(response_for(plan.batches[0], full))
    data["plan_id"] = altered_plan.batches[0].plan_id
    result = assess_plan(altered_plan, altered, sources, [json.dumps(data)], "fake-key")
    assert old.evidence[0].facts["ack"] == altered.evidence[0].facts["ack"]
    assert (
        result.status == "no_qualified_case"
        and result.reason == "unbound_or_cosmetic_change"
    )


def test_secret_escaped_output_and_oversize_are_rejected_before_application():
    plan, _, _, full = prepared()
    batch = plan.batches[0]
    with pytest.raises(CapacityError):
        decode_batch("x" * (RESPONSE_BYTES + 1), batch, "fake-key")
    data = json.loads(response_for(batch, full))
    data["explanations"][0] = "forbidden-current-secret"
    raw = json.dumps(data).replace(
        "forbidden-current-secret", "\\u0066orbidden-current-secret"
    )
    with pytest.raises(ValueError):
        decode_batch(raw, batch, "forbidden-current-secret")


def test_changed_snapshot_cannot_reuse_old_plan_identity():
    plan, new, sources, full = prepared()
    changed = plan.snapshot.model_dump()
    changed["cases"][0]["task"] = "changed frozen task"
    snapshot = HistorySnapshot.model_validate(changed)
    altered = plan.model_copy(update={"snapshot": snapshot})
    with pytest.raises(ValueError, match="plan identity"):
        assess_plan(
            altered,
            new,
            sources,
            [response_for(b, full) for b in plan.batches],
            "fake-key",
        )


def test_empty_history_still_gets_complete_new_case_and_stage_observation_inspection():
    from app.training.boss_stages import PROMOTION_STAGES
    from tests.test_boss_stages import facts

    args = facts(PROMOTION_STAGES[-1])
    plan = plan_comparison(
        freeze_history({}),
        args["case"],
        args["sources"],
        "controlled-model",
        "fake-key",
        stage=args["stage"],
    )
    assert len(plan.batches) == 1 and plan.batches[0].pairs == []
    assert len(plan.batches[0].new.citations) == len(args["case"].evidence)
    assert set(plan.batches[0].criteria) == {
        o.source_capability for m in args["stage"].mandatory for o in m.observations
    }
    data = json.loads(response_for(plan.batches[0], []))
    data["coverage"] = [c.model_dump(mode="json") for c in args["coverage"]]
    assert (
        assess_plan(
            plan, args["case"], args["sources"], [json.dumps(data)], "fake-key"
        ).status
        == "novelty_candidate"
    )
    data["coverage"].pop()
    with pytest.raises(ValueError, match="incomplete Boss"):
        assess_plan(plan, args["case"], args["sources"], [json.dumps(data)], "fake-key")


def test_checkpoint_roundtrip_and_foreign_frozen_context_are_distinguished():
    from app.training.history_protocol import ComparisonPlan

    plan, new, sources, full = prepared()
    restored = ComparisonPlan.model_validate_json(plan.model_dump_json())
    response = response_for(restored.batches[0], full)
    assert (
        assess_plan(restored, new, sources, [response], "fake-key").status
        == "novelty_candidate"
    )
    data = restored.model_dump()
    data["batches"][0]["seen"][0]["task"] = "tampered model input"
    changed = ComparisonPlan.model_validate(data)
    with pytest.raises(ValueError, match="frozen comparison context"):
        assess_plan(changed, new, sources, [response], "fake-key")
    broken = restored.batches[0].model_copy(update={"pairs": [(0, 999, 0)]})
    with pytest.raises(ValueError, match="input pair"):
        wire_request(broken, restored.model_id)
    with pytest.raises(ValueError, match="input pair"):
        decode_batch(response, broken, "fake-key")


def test_small_reference_response_cannot_expand_without_a_bound():
    plan, _, _, full = prepared(600, 1)
    batch = plan.batches[0]
    data = json.loads(response_for(batch, full))
    data["explanations"] = ["实际因果说明" * 1000]
    raw = json.dumps(data, ensure_ascii=False)
    assert len(raw.encode()) < RESPONSE_BYTES
    with pytest.raises(CapacityError, match="reference_expansion"):
        decode_batch(raw, batch, "fake-key")


def test_same_decision_can_require_different_evidence_without_inventing_a_new_answer():
    history, new, sources, full = fixture(1, 1)
    old = next(iter(history.values()))
    data = new.model_dump()
    data["evidence"][0]["facts"]["ack"] = "received_but_not_committed"
    data["variation"]["expected_evidence"] = "事务提交记录"
    for judgment in data["judgments"]:
        judgment["options"] = old.judgments[0].options
    for rule in data["rubric"]:
        rule["acceptable_options"] = old.rubric[0].acceptable_options
        rule["reasoning"] = "收件已知而提交仍不明，须核对事务提交记录"
    new = type(new).model_validate(data)
    explicit = []
    for comparison in full:
        change = comparison.changes[0].model_dump()
        change.update(
            dimension="expected_evidence",
            effect="different_required_evidence",
            after={
                "evidence_id": "e1",
                "fact": "ack",
                "value": "received_but_not_committed",
            },
            before_variation=old.variation.expected_evidence,
            after_variation=new.variation.expected_evidence,
            after_reasoning=new.rubric[0].reasoning,
            before_consequence=old.variation.expected_evidence,
            after_consequence=new.variation.expected_evidence,
        )
        from app.training.independent_novelty import ScenarioChange

        explicit.append(
            comparison.model_copy(
                update={"changes": [ScenarioChange.model_validate(change)]}
            )
        )
    plan = plan_comparison(
        freeze_history(history), new, sources, "controlled-model", "fake-key"
    )
    raw = response_for(plan.batches[0], explicit)
    assert (
        assess_plan(plan, new, sources, [raw], "fake-key").status == "novelty_candidate"
    )
    changed = json.loads(raw)
    changed["changes"][0]["ac"] = 1
    with pytest.raises(ValueError, match="expected-evidence reference"):
        decode_batch(json.dumps(changed), plan.batches[0], "fake-key")


def test_chinese_order_consequences_are_exactly_the_existing_semantic_values():
    from app.training.independent_novelty import _decisions

    history, new, sources, full = fixture(1, 1)
    run_id, old = next(iter(history.items()))
    old_data = old.model_dump()
    old_data["judgments"][0]["kind"] = "order"
    old_data["rubric"][0].update(acceptable_options=[], acceptable_orders=[[0, 1, 2]])
    old = type(old).model_validate(old_data)
    new_data = new.model_dump()
    new_data["judgments"] = new_data["judgments"][:1]
    new_data["rubric"] = new_data["rubric"][:1]
    new_data["judgments"][0].update(
        kind="order", options=["保留已提交结果", "核对提交记录", "退出重复执行"]
    )
    new_data["rubric"][0].update(acceptable_options=[], acceptable_orders=[[0, 1, 2]])
    new = type(new).model_validate(new_data)
    before = next(iter(_decisions(old, old.rubric[0])))
    after = next(iter(_decisions(new, new.rubric[0])))
    assert "\\u" not in before and "先核对处理记录" in before
    assert context(old).rubric[0].consequences == [before]
    change = (
        full[0]
        .changes[0]
        .model_copy(update={"before_consequence": before, "after_consequence": after})
    )
    comparison = full[0].model_copy(update={"changes": [change]})
    plan = plan_comparison(
        freeze_history({run_id: old}), new, sources, "controlled-model", "fake-key"
    )
    response = response_for(plan.batches[0], [comparison])
    assert decode_batch(response, plan.batches[0], "fake-key") == [comparison]
    assert (
        assess_plan(plan, new, sources, [response], "fake-key").status
        == "novelty_candidate"
    )
