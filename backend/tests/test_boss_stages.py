"""Controlled full-facet rule witnesses; no real-model teaching certification."""

import copy
import json

import pytest

from app.capabilities.catalog import CATALOG
from app.training.boss_stages import (
    AI_CHALLENGE,
    PROMOTION_STAGES,
    STAGES,
    ObservationCoverage,
    assess_stage,
    next_boss,
    validate_stage_coverage,
    validate_stage_mapping,
)
from app.training.evaluation_schema import evaluation_inputs
from app.training.independent_novelty import assess_novelty
from app.training.schema import Candidate, Source
from tests.test_evaluation_schema import example
from tests.test_independent import delivery

# One explicit situation per judgment. Supporting observations are actual facts,
# not the standard's scope label copied into an otherwise identical question.
SITUATIONS = {
    (300, "boundary"): (
        "订单模块已提交，通知模块发送失败",
        "订单状态归订单模块，通知失败应在通知边界重试",
        ["订单模块持有订单状态；通知模块仅消费订单事件"],
    ),
    (300, "consistency"): (
        "两事务均读到库存1并各扣1",
        "读后检查无法防止并发超卖，须在提交边界保护库存约束",
        ["两事务均在另一事务提交前读取库存1"],
    ),
    (300, "locate"): (
        "TLS握手完成，但代理返回502",
        "应补代理到应用的连接证据，不能把失败归因DNS",
        ["客户端DNS成功、TLS握手完成、代理返回502、应用未见请求"],
    ),
    (700, "concurrency"): (
        "两个线程读旧计数后分别写回",
        "共享计数的读改写交错会丢失更新，保护须覆盖整个读改写",
        ["线程A读0、线程B读0、A写1、B写1"],
    ),
    (700, "authorization"): (
        "用户B带入用户A的文档ID",
        "认证成功不等于资源授权，读取前须核文档归属",
        ["B已登录；文档归A；查询只按文档ID"],
    ),
    (700, "recovery"): (
        "新版已改变数据格式，旧镜像仅识别旧格式",
        "仅回退镜像不能恢复数据，应按恢复点还原或兼容迁移后核对",
        ["新版数据已持久；旧镜像无法读取；发布前有可核验恢复点"],
    ),
    (700, "verify"): (
        "恢复后首页能打开但尚未检查写入",
        "恢复验收需覆盖正常与失败写入及重读后的持久结果",
        ["首页200；写入、拒绝写入和重启后重读均未测"],
    ),
    (1500, "tradeoff"): (
        "更短保留期降低存储却破坏审计要求",
        "必须满足审计期限，再比较分层存储成本，不能只追求最低存储",
        ["审计要求一年；当前90天；一年热存成本超预算但归档可满足读取时限"],
    ),
    (1500, "evolution"): (
        "旧读者尚在线，新写者拟删旧字段",
        "先兼容双读写再迁移验证，最后停止旧读者并删除字段",
        ["旧读者只识别旧字段；新版本可双写；迁移尚未完成"],
    ),
    (1500, "containment"): (
        "新版本只在一个分区导致坏写入",
        "先停止该分区发布和坏写入，再核恢复范围，避免扩大至全部分区",
        ["分区A坏写入；B正常；继续全量发布会扩散同一路径"],
    ),
    (3000, "transfer"): (
        "新背景变成离线设备批量补传，不能沿用在线确认假设",
        "离线重复补传需识别事件身份；在线连接成功经验不足以判断一次处理",
        [
            "新情境允许离线重复补传，原在线同步确认条件已改变",
            "设备持有待传事件，服务端持有持久接收记录，重连不等于事件首次到达",
        ],
    ),
    (3000, "counterexample"): (
        "内存替身全绿而数据库锁等待未覆盖",
        "引入真实事务交错与中断能检验当前样本未触及的等待和恢复风险",
        ["样本只用单线程内存替身；实际生产依赖事务锁与进程重启"],
    ),
    (3000, "review"): (
        "服务函数新增校验但批处理调用绕过该函数",
        "审查必须沿批处理调用验证拒绝路径，不能以单元测试绿色认定全入口受保护",
        ["HTTP调用受检函数；批处理直接写表；现测试仅HTTP"],
    ),
    (6000, "diagnosis"): (
        "吞吐下降但CPU空闲，队列积压",
        "事务锁等待延长确认时间导致队列积压，需锁持有与任务确认时序共同定位",
        [
            "p99增长、CPU低、等待时间主导",
            "长事务持有行锁，任务写入阻塞等待该锁",
            "队列消费在持久写入后确认，未确认任务重试并加剧等待",
        ],
    ),
    (6000, "risk"): (
        "跳过持久确认可清队列但可能丢任务",
        "队列长度不能抵消数据丢失风险，应比较限流与恢复吞吐的代价",
        ["业务不接受任务丢失；允许延迟；跳过确认可降低队列但无法恢复丢失任务"],
    ),
    (6000, "verification"): (
        "已调整事务范围但仅测成功一次",
        "应验证并发、中断、重试及持久结果不重不丢，不能只看一次响应",
        ["单次响应成功；重复提交与写入后崩溃尚未验证"],
    ),
    (6000, "rollback"): (
        "回退旧版本将读取已变更结构的数据",
        "先判断兼容与数据恢复点，再回退并重读业务记录核实",
        ["新写入格式旧版本不能读；有备份和变更日志；回退镜像本身不还原数据"],
    ),
}


def facts(stage):
    base, _, original, initial_grade = example("choice")
    data = base.model_dump()
    data.update(
        target=stage.mandatory[0].target.model_dump(),
        judgments=[],
        rubric=[],
        evidence=[],
        task="根据当前冻结情境完成各必考判断及相关理由",
        assumptions=["受控教学材料，不是生产事件"],
    )
    sources = {}
    grades, answers, coverage = [], [], []
    criteria = {c.id: c.criterion for d in CATALOG.domains for c in d.capabilities}
    for m in stage.mandatory:
        prompt, reasoning, observed = SITUATIONS[stage.launch_points, m.judgment_id]
        assert len(observed) == len(m.observations)
        evidence_ids = []
        for observation, value in zip(m.observations, observed, strict=True):
            source_id = "boss-" + observation.source_capability
            source = Source(
                id=source_id,
                url="https://example.com/controlled/" + observation.source_capability,
                version="synthetic-v1",
                locator="controlled requirement",
                text=criteria[observation.source_capability],
            )
            sources[source_id] = source
            eid = m.judgment_id + "-" + observation.id
            evidence_ids.append(eid)
            data["evidence"].append(
                {
                    "id": eid,
                    "label": "教学材料",
                    "text": value,
                    "facts": {eid: value},
                    "citations": [{"source_id": source_id, "quote": source.text}],
                }
            )
            coverage.append(
                ObservationCoverage(
                    judgment_id=m.judgment_id,
                    observation_id=observation.id,
                    requirement_quote=observation.requirement,
                    criterion_quote=source.text,
                    prompt_quote=prompt,
                    reasoning_quote=reasoning,
                    evidence_id=eid,
                    fact=eid,
                    value=value,
                    source_id=source_id,
                    assessment="matches",
                    explanation="此受控观察对应冻结要求；语义仍需独立样本校准",
                )
            )
        data["judgments"].append(
            {
                "id": m.judgment_id,
                "kind": "choice",
                "prompt": prompt,
                "options": [reasoning, "材料提及相关组件，所以可直接认定没有风险"],
                "evidence_ids": evidence_ids,
            }
        )
        data["rubric"].append(
            {
                "judgment_id": m.judgment_id,
                "acceptable_options": [0],
                "reasoning": reasoning,
                "evidence_ids": evidence_ids,
                "counterexample": observed[-1],
                "help_boundary": "不得提前交付该判断答案",
            }
        )
        answers.append({"judgment_id": m.judgment_id, "value": 0, "reason": reasoning})
        grade = copy.deepcopy(initial_grade["items"][0])
        material = data["evidence"][-1]
        grade.update(
            judgment_id=m.judgment_id,
            rule_quote=reasoning,
            answer_quotes=[
                {"input": "original", "field": "reason", "quote": reasoning}
            ],
            grounding=[
                {
                    "evidence_id": material["id"],
                    "fact": material["id"],
                    "value": observed[-1],
                    "citation": material["citations"][0],
                }
            ],
            reason_claims=[
                {
                    "answer_quote": 0,
                    "grounding": 0,
                    "interpreted_fact_value": observed[-1],
                }
            ],
            explanation="原答对应所列观察及冻结规则；这是受控判据样本",
        )
        materials = [e for e in data["evidence"] if e["id"] in evidence_ids]
        grade["grounding"] = [
            {
                "evidence_id": e["id"],
                "fact": e["id"],
                "value": e["facts"][e["id"]],
                "citation": e["citations"][0],
            }
            for e in materials
        ]
        grade["reason_claims"] = [
            {
                "answer_quote": 0,
                "grounding": i,
                "interpreted_fact_value": e["facts"][e["id"]],
            }
            for i, e in enumerate(materials)
        ]
        grades.append(grade)
    case = Candidate.model_validate(data)
    original.answers = answers
    return {
        "stage": stage,
        "launch_points": stage.launch_points,
        "current_level": stage.from_level,
        "run_id": original.run_id,
        "mode": "independent",
        "freeze_sequence": 10,
        "case": case,
        "sources": list(sources.values()),
        "inputs": evaluation_inputs([original]),
        "grading_raw": json.dumps({"items": grades}),
        "novelty": assess_novelty(case, list(sources.values()), {}, [], "fake-key"),
        "deliveries": [],
        "key": "fake-key",
        "coverage": coverage,
    }


@pytest.mark.parametrize("stage", STAGES, ids=lambda s: s.version)
def test_released_standards_threshold_no_jump_and_full_facet_witness(stage):
    assert next_boss(stage.from_level, stage.launch_points - 1) is None
    assert next_boss(stage.from_level, stage.launch_points) == stage
    assert next_boss(stage.from_level, 999999) == stage
    args = facts(stage)
    before = args["case"].model_dump_json(), args["inputs"].model_dump_json()
    result = assess_stage(**args)
    assert result.outcome == "independent_pass_candidate"
    assert result.promote_to == stage.to_level and not result.shortfalls
    assert result.semantic_reliability == "unverified"
    assert (args["case"].model_dump_json(), args["inputs"].model_dump_json()) == before
    assert (
        assess_stage(**(args | {"launch_points": stage.launch_points - 1})).outcome
        == "not_admitted"
    )
    assert len({m.judgment_id for m in stage.mandatory}) == len(stage.mandatory)
    assert 3 <= len(stage.mandatory) <= 4


@pytest.mark.parametrize("points", [True, -1, 700.5])
def test_bad_points_are_not_coerced(points):
    with pytest.raises(ValueError):
        next_boss("中级程序员", points)


def test_first_stage_entry_unchanged_and_top_keeps_challenge_without_next_level():
    assert next_boss("小白程序员", 6000) is None  # existing first-stage entry
    assert AI_CHALLENGE.to_level is None
    assert AI_CHALLENGE.mandatory == PROMOTION_STAGES[-1].mandatory
    assert len(PROMOTION_STAGES) == 5


def failed(args, index):
    grade = json.loads(args["grading_raw"])
    item = grade["items"][index]
    item.update(
        conclusion="evidenced_fail",
        interpreted_reasoning=1,
        counterexample_quote=args["case"].rubric[index].counterexample,
        gap="该理由忽略了冻结材料中列出的反例",
    )
    return args | {"grading_raw": json.dumps(grade)}


@pytest.mark.parametrize("stage", STAGES, ids=lambda s: s.version)
def test_every_failed_item_blocks_promotion_and_late_result_keeps_only_its_key(stage):
    args = facts(stage)
    for index, mandatory in enumerate(stage.mandatory):
        failure = failed(args, index)
        result = assess_stage(**failure)
        assert result.outcome == "evidenced_fail" and result.promote_to is None
        assert len(result.shortfalls) == 1
        assert result.shortfalls[0].target == mandatory.target
        assert assess_stage(**(failure | {"current_level": "AI级程序员"})) == result
    late = assess_stage(**(args | {"current_level": "AI级程序员"}))
    assert late.outcome == "independent_pass_candidate" and late.promote_to is None


@pytest.mark.parametrize("stage", STAGES, ids=lambda s: s.version)
def test_missing_or_unclear_facets_and_altered_standards_never_promote(stage):
    args = facts(stage)
    for index in range(len(args["coverage"])):
        missing = args["coverage"][:index] + args["coverage"][index + 1 :]
        assert assess_stage(**(args | {"coverage": missing})).outcome == "invalid_case"
    for change in [
        {"assessment": "unclear"},
        {"source_id": "invented"},
        {"value": "not observed"},
        {"requirement_quote": "只提到组件即可"},
        {"prompt_quote": "模型说涵盖所有要求"},
        {"criterion_quote": "模型高自信"},
    ]:
        claims = [args["coverage"][0].model_copy(update=change), *args["coverage"][1:]]
        with pytest.raises(ValueError):
            validate_stage_coverage(stage, args["case"], claims)
    with pytest.raises(ValueError):
        validate_stage_mapping(
            stage.model_copy(update={"launch_points": 1}), args["case"]
        )
    with pytest.raises(ValueError):
        validate_stage_mapping(
            stage,
            args["case"].model_copy(update={"judgments": args["case"].judgments[:-1]}),
        )


@pytest.mark.parametrize("stage", STAGES, ids=lambda s: s.version)
def test_ineligible_and_uncertain_results_never_make_independent_shortfalls(stage):
    args = facts(stage)
    unknown = delivery(2, status="delivery_unknown").model_copy(
        update={"run_id": args["run_id"]}
    )
    for change, expected in [
        ({"mode": "practice"}, "practice"),
        ({"converted_sequence": 2}, "practice"),
        ({"disputed": True}, "disputed"),
        ({"grading_raw": None}, "system_failure"),
        ({"deliveries": [unknown]}, "pending_delivery"),
        (
            {
                "novelty": args["novelty"].model_copy(
                    update={"status": "no_qualified_case"}
                )
            },
            "no_qualified_case",
        ),
    ]:
        result = assess_stage(**(failed(args, 0) | change))
        assert (
            result.outcome == expected
            and result.promote_to is None
            and not result.shortfalls
        )
    pending = assess_stage(**(args | {"pending_revalidation": True}))
    assert pending.promote_to is None
    assert pending.outcome == (
        "pending_revalidation" if stage.to_level else "independent_pass_candidate"
    )
    late = delivery(12, attempt_id=unknown.id, exposure_sequence=2).model_copy(
        update={"run_id": args["run_id"]}
    )
    assert (
        assess_stage(**(args | {"deliveries": [unknown, late]})).outcome == "practice"
    )
    after = delivery(12).model_copy(update={"run_id": args["run_id"]})
    assert assess_stage(**(args | {"deliveries": [after]})).promote_to == stage.to_level
    grade = json.loads(args["grading_raw"])
    grade["items"][0].update(conclusion="unclear", gap="不能确认理由的意思")
    result = assess_stage(**(args | {"grading_raw": json.dumps(grade)}))
    assert result.outcome == "unclear" and not result.shortfalls


def test_multidomain_diagnosis_freezes_three_distinct_supporting_sources_not_three_awards():
    stage = PROMOTION_STAGES[-1]
    args = facts(stage)
    diagnosis = stage.mandatory[0]
    assert {o.source_capability for o in diagnosis.observations} == {
        "performance.bottleneck",
        "data.query",
        "async.jobs",
    }
    result = assess_stage(**failed(args, 0))
    assert [s.target.capability_id for s in result.shortfalls] == [
        "performance.bottleneck"
    ]
    claims = [c for c in args["coverage"] if c.judgment_id == diagnosis.judgment_id]
    assert len({c.evidence_id for c in claims}) == 3
    assert len({c.source_id for c in claims}) == 3


def test_composite_pass_needs_reason_grounding_for_each_observed_domain():
    args = facts(PROMOTION_STAGES[-1])
    grade = json.loads(args["grading_raw"])
    assert len(grade["items"][0]["reason_claims"]) == 3
    grade["items"][0]["reason_claims"].pop()
    result = assess_stage(**(args | {"grading_raw": json.dumps(grade)}))
    assert (
        result.outcome == "unclear"
        and result.promote_to is None
        and not result.shortfalls
    )
