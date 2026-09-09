"""Controlled causal variants; fixture evidence, not a teaching-quality claim."""

from app.training.schema import Candidate

SCENARIOS = [
    (
        "committed",
        "事务已提交且收到成功确认。",
        "保留已提交结果，不再次执行事务",
        "提交成功确认",
        "收到成功确认后重执行会重复处理。",
    ),
    (
        "rejected",
        "请求在执行前被权限检查拒绝，审计日志确认无写入。",
        "修复权限并重新申请授权",
        "执行前权限拒绝日志",
        "请求在执行前被拒绝，应先解决授权问题。",
    ),
    (
        "running",
        "服务端状态显示任务仍在执行，尚未提交。",
        "等待现有任务状态，不重复启动",
        "正在执行的任务记录",
        "已有任务正在执行，应继续跟踪原任务。",
    ),
    (
        "rolled_back",
        "数据库明确记录该事务已回滚，没有持久写入。",
        "查明回滚原因后决定是否重新提交",
        "事务回滚记录",
        "回滚有明确证据，应核对原因后处理。",
    ),
    (
        "duplicated",
        "幂等记录显示重复请求已返回首次完成结果。",
        "使用首次结果并核对幂等记录",
        "首次完成及幂等命中记录",
        "重复请求命中既有结果，不需要再次执行业务。",
    ),
]


def scenario(base: Candidate, index: int) -> Candidate:
    fact, text, decision, evidence, reason = SCENARIOS[index]
    data = base.model_dump()
    data["evidence"][0]["facts"] = {"ack": fact}
    data["evidence"][0]["text"] = text
    data["judgments"][0]["options"][0] = decision
    data["rubric"][0]["acceptable_options"] = [0]
    data["rubric"][0]["reasoning"] = reason
    data["variation"] = {
        "causal_condition": text,
        "expected_evidence": evidence,
        "decision_effect": decision,
    }
    return Candidate.model_validate(data)


def comparisons(context):
    new = context["new"]
    result = []
    for seen in context["seen"]:
        old = seen["case"]
        before, after = old["rubric"][0], new["rubric"][0]
        result.append(
            {
                "seen_run_id": seen["run_id"],
                "seen_judgment_id": "j1",
                "new_judgment_id": "j1",
                "relation": "different_causal_scenario",
                "changes": [
                    {
                        "dimension": "causal_condition",
                        "before": {
                            "evidence_id": "e1",
                            "fact": "ack",
                            "value": old["evidence"][0]["facts"]["ack"],
                        },
                        "after": {
                            "evidence_id": "e1",
                            "fact": "ack",
                            "value": new["evidence"][0]["facts"]["ack"],
                        },
                        "before_variation": old["variation"]["causal_condition"],
                        "after_variation": new["variation"]["causal_condition"],
                        "before_reasoning": before["reasoning"],
                        "after_reasoning": after["reasoning"],
                        "before_consequence": old["judgments"][0]["options"][
                            before["acceptable_options"][0]
                        ],
                        "after_consequence": new["judgments"][0]["options"][
                            after["acceptable_options"][0]
                        ],
                        "effect": "different_decision",
                        "explanation": "实际执行状态和证据不同，需要采取各自材料对应的行动。",
                    }
                ],
            }
        )
    return {"comparisons": result}
