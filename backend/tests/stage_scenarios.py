"""Controlled full-facet provider witnesses, not model-quality certification."""

import json

from app.training.boss_stages import PROMOTION_STAGES, BossStage
from app.training.schema import Candidate, Source
from tests.test_boss_stages import facts
from tests.test_evaluations import grading

REFERENCE = "Controlled reference: inspect ownership, concurrent persistence, authorization, recovery, verification, migration and operational risk against observable evidence."


def public_history_cases(count):
    """Complete controlled public fixtures, not awarded points or generated claims."""
    templates = [facts(stage) for stage in PROMOTION_STAGES[:2]]
    for number in range(count):
        fixture = templates[number % len(templates)]
        data = fixture["case"].model_dump(mode="json")
        # Preserve each full round and actual observations. Different measured
        # delay is not, by itself, a declaration that these old cases are novel.
        for evidence in data["evidence"]:
            evidence["facts"]["observed_delay_ms"] = str(100 + number)
            evidence["text"] += f"；当前记录处理延迟{100 + number}毫秒"
            for citation in evidence["citations"]:
                citation["quote"] = REFERENCE
        data["assumptions"].append(f"当前观测窗口处理延迟为{100 + number}毫秒")
        sources = [
            Source.model_validate(s.model_dump() | {"text": REFERENCE})
            for s in fixture["sources"]
        ]
        yield Candidate.model_validate_json(json.dumps(data)), sources


def candidate(payload):
    body = json.loads(payload["messages"][1]["content"])
    if "input" in body:
        batch = body["input"]
        stage = BossStage.model_validate_json(json.dumps(batch["stage"]))
        changes, rows = [], []
        for pair, (run_index, old_j, new_j) in enumerate(batch["pairs"]):
            old = batch["seen"][batch["runs"][run_index]["case"]]
            new = batch["new"]
            before = next(
                i
                for i, r in enumerate(old["rubric"])
                if r["judgment_id"] == old["judgments"][old_j]["id"]
            )
            after = next(
                i
                for i, r in enumerate(new["rubric"])
                if r["judgment_id"] == new["judgments"][new_j]["id"]
            )
            b = next(
                i
                for i, f in enumerate(old["facts"])
                if f["evidence_id"] in old["rubric"][before]["evidence_ids"]
            )
            a = next(
                i
                for i, f in enumerate(new["facts"])
                if f["evidence_id"] in new["rubric"][after]["evidence_ids"]
            )
            # Distinct actual observations and actions, not renamed IDs.
            assert old["facts"][b]["value"] != new["facts"][a]["value"]
            assert (
                old["rubric"][before]["consequences"][0]
                != new["rubric"][after]["consequences"][0]
            )
            changes.append(
                {
                    "c": batch["runs"][run_index]["case"],
                    "r": before,
                    "n": after,
                    "b": b,
                    "a": a,
                    "d": "cause",
                    "e": "decision",
                    "bc": 0,
                    "ac": 0,
                    "x": 0,
                }
            )
            rows.append([pair, "different", [len(changes) - 1]])
        return {
            "version": "comparison-references-v1",
            "plan_id": batch["plan_id"],
            "batch": batch["batch"],
            "explanations": [
                "旧判断针对原记录中的边界或约束；新判断须根据其不同的故障与风险观察选择对应行动，不能沿用旧答案。"
            ]
            if rows
            else [],
            "changes": changes,
            "comparisons": rows,
            "coverage": [c.model_dump(mode="json") for c in facts(stage)["coverage"]],
        }
    stage = BossStage.model_validate_json(json.dumps(body["boss_standard"]))
    result = facts(stage)["case"].model_dump(mode="json")
    sources = {s["id"]: s for s in body["sources"]}
    for evidence in result["evidence"]:
        for citation in evidence["citations"]:
            citation["quote"] = sources[citation["source_id"]]["text"]
    return result


def grade(context):
    result = grading(context)
    for item in result["items"]:
        rule = next(
            r
            for r in context["task"]["rubric"]
            if r["judgment_id"] == item["judgment_id"]
        )
        materials = [
            e for e in context["task"]["evidence"] if e["id"] in rule["evidence_ids"]
        ]
        item["grounding"] = [
            {
                "evidence_id": e["id"],
                "fact": fact,
                "value": value,
                "citation": e["citations"][0],
            }
            for e in materials
            for fact, value in e["facts"].items()
        ]
        item["reason_claims"] = [
            {"answer_quote": 0, "grounding": i, "interpreted_fact_value": g["value"]}
            for i, g in enumerate(item["grounding"])
        ]
        if item["interpreted_value"] == 1:
            item.update(
                conclusion="evidenced_fail",
                gap="该判断遗漏冻结观察所要求的风险约束",
                counterexample_quote=rule["counterexample"],
            )
    return result
