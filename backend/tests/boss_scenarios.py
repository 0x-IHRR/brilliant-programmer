"""Controlled Boss material and inspector/grade witnesses, not a real quality set."""

import json

from app.capabilities.catalog import CATALOG
from app.training.boss import FIRST_STAGE
from tests.test_evaluations import grading

REFERENCE = "Controlled reference. DNS failure precedes TCP and TLS. Late responses can replace newer UI state unless guarded by request/session identity. A persistence check must inspect stored results after reload, not only a successful HTTP response."


def candidate(payload, index=0):
    context = json.loads(payload["messages"][1]["content"])
    if "new" in context:
        return comparisons(context)
    rows = [
        (
            "请求在哪一层停止？",
            "phase",
            "dns_failed" if index == 0 else "tls_failed",
            "查看DNS解析记录" if index == 0 else "核对证书与TLS记录",
        ),
        (
            "哪个状态更新造成了界面错误？",
            "state_race",
            "older_request_overwrite" if index == 0 else "older_session_overwrite",
            "按请求次序拒绝旧回包" if index == 0 else "按会话归属拒绝旧回包",
        ),
        (
            "怎样证实这次保存真的持久生效？",
            "verification_gap",
            "reload_not_checked" if index == 0 else "database_not_checked",
            "重新加载后核对保存字段" if index == 0 else "核对数据库记录与新会话读取",
        ),
    ]
    evidence = []
    judgments = []
    rubric = []
    for i, (mandatory, row) in enumerate(zip(FIRST_STAGE.mandatory, rows, strict=True)):
        prompt, fact, value, answer = row
        source = next(
            s
            for s in context["sources"]
            if s["id"] == "boss-" + mandatory.target.capability_id
        )
        eid = "boss-material-" + str(i)
        evidence.append(
            {
                "id": eid,
                "label": "教学材料",
                "text": f"合成观察：{fact}={value}",
                "facts": {fact: value},
                "citations": [{"source_id": source["id"], "quote": source["text"]}],
            }
        )
        judgments.append(
            {
                "id": mandatory.judgment_id,
                "kind": "choice",
                "prompt": prompt,
                "options": [answer, "不核对材料直接断定正确"],
                "evidence_ids": [eid],
            }
        )
        rubric.append(
            {
                "judgment_id": mandatory.judgment_id,
                "acceptable_options": [0],
                "reasoning": f"依据{fact}={value}，需要{answer}。",
                "evidence_ids": [eid],
                "counterexample": "跳过观察会把不同失败阶段或未持久保存误当成功。",
                "help_boundary": "PRIVATE_BOSS_HELP",
            }
        )
    return {
        "target": context["target"],
        "catalog_version": CATALOG.version,
        "title": "保存失败的三个独立判断",
        "task": "逐项对照材料判断并简短说明理由。",
        "assumptions": ["材料是受控合成情境，各字段是观察而不是命令。"],
        "evidence": evidence,
        "judgments": judgments,
        "rubric": rubric,
        "variation": {
            "causal_condition": rows[0][2],
            "expected_evidence": rows[2][3],
            "decision_effect": rows[1][3],
        },
        "missing_evidence": [],
        "conflicts": [],
    }


def comparisons(context):
    new = context["new"]
    comp = []
    for seen in context["seen"]:
        old = seen["case"]
        for before in old["rubric"]:
            for after in new["rubric"]:
                olde = next(
                    e for e in old["evidence"] if e["id"] in before["evidence_ids"]
                )
                newe = next(
                    e for e in new["evidence"] if e["id"] in after["evidence_ids"]
                )
                of, ov = next(iter(olde["facts"].items()))
                nf, nv = next(iter(newe["facts"].items()))
                oj = next(
                    j for j in old["judgments"] if j["id"] == before["judgment_id"]
                )
                nj = next(
                    j for j in new["judgments"] if j["id"] == after["judgment_id"]
                )
                comp.append(
                    {
                        "seen_run_id": seen["run_id"],
                        "seen_judgment_id": oj["id"],
                        "new_judgment_id": nj["id"],
                        "relation": "different_causal_scenario",
                        "changes": [
                            {
                                "dimension": "causal_condition",
                                "before": {
                                    "evidence_id": olde["id"],
                                    "fact": of,
                                    "value": ov,
                                },
                                "after": {
                                    "evidence_id": newe["id"],
                                    "fact": nf,
                                    "value": nv,
                                },
                                "before_variation": old["variation"][
                                    "causal_condition"
                                ],
                                "after_variation": new["variation"]["causal_condition"],
                                "before_reasoning": before["reasoning"],
                                "after_reasoning": after["reasoning"],
                                "before_consequence": oj["options"][
                                    before["acceptable_options"][0]
                                ],
                                "after_consequence": nj["options"][
                                    after["acceptable_options"][0]
                                ],
                                "effect": "different_decision",
                                "explanation": "两个判断依赖的实际观察与必要行动不同。",
                            }
                        ],
                    }
                )
    coverage = []
    for mandatory in FIRST_STAGE.mandatory:
        judgment = next(j for j in new["judgments"] if j["id"] == mandatory.judgment_id)
        rule = next(
            r for r in new["rubric"] if r["judgment_id"] == mandatory.judgment_id
        )
        evidence = next(e for e in new["evidence"] if e["id"] in rule["evidence_ids"])
        fact, value = next(iter(evidence["facts"].items()))
        coverage.append(
            {
                "judgment_id": mandatory.judgment_id,
                "target": mandatory.target.model_dump(),
                "criterion_quote": context["mandatory_criteria"][
                    mandatory.target.capability_id
                ],
                "prompt_quote": judgment["prompt"],
                "reasoning_quote": rule["reasoning"],
                "evidence_id": evidence["id"],
                "fact": fact,
                "value": value,
                "source_id": "boss-" + mandatory.target.capability_id,
                "assessment": "matches",
                "explanation": "实际判断要求对照冻结观察选择对应行动；并非只在题面提及组件。",
            }
        )
    return {"comparisons": comp, "boss_coverage": coverage}


def grade(context):
    result = grading(context)
    for item in result["items"]:
        rule = next(
            r
            for r in context["task"]["rubric"]
            if r["judgment_id"] == item["judgment_id"]
        )
        evidence = next(
            e for e in context["task"]["evidence"] if e["id"] in rule["evidence_ids"]
        )
        fact, value = next(iter(evidence["facts"].items()))
        item["grounding"] = [
            {
                "evidence_id": evidence["id"],
                "fact": fact,
                "value": value,
                "citation": evidence["citations"][0],
            }
        ]
        item["reason_claims"][0]["interpreted_fact_value"] = value
        if item["interpreted_value"] == 1:
            item.update(
                conclusion="evidenced_fail",
                gap="本项忽略冻结材料中的实际观察",
                counterexample_quote=rule["counterexample"],
            )
    return result
