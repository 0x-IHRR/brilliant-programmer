"""Released later Boss standards; pure proposals, no admission/promotion writes.

The caller displays and persists this exact version before generation, captures
launch-time points/level, and settles once under the owner lock. Coverage claims
remain inspected model interpretations, not semantic or career certification.
"""

import json
import uuid
from typing import Any, Literal

from app.capabilities.catalog import CATALOG, EvidenceKey
from app.training.boss import (
    FIRST_STAGE,
    ConfirmedShortfall,
    FirstStage,
    assess_mapped_boss,
)
from app.training.evaluation_schema import (
    EvaluationInputs,
    GradingItem,
    validate_grading,
)
from app.training.independent import Mode, OrderedDelivery, Outcome
from app.training.independent_novelty import NoveltyAssessment
from app.training.schema import Candidate, Source, Strict, Text

Level = Literal[
    "初级程序员", "中级程序员", "高级程序员", "牛逼程序员", "传奇程序员", "AI级程序员"
]


class Observation(Strict):
    id: Text
    requirement: Text
    # Supporting domain source, not another awarded EvidenceKey.
    source_capability: Text


class StageJudgment(Strict):
    judgment_id: Text
    scope: Text
    target: EvidenceKey
    observations: tuple[Observation, ...]


class BossStage(Strict):
    version: Text
    catalog_version: Text
    from_level: Level
    to_level: Level | None
    launch_points: int
    mandatory: tuple[StageJudgment, ...]
    passing_rule: Text


def _item(
    id: str,
    scope: str,
    capability: str,
    difficulty: Literal["进阶", "综合"],
    observations: tuple[tuple[str, str, str], ...],
) -> StageJudgment:
    return StageJudgment(
        judgment_id=id,
        scope=scope,
        target=EvidenceKey(
            capability_id=capability,
            difficulty=difficulty,
            background_id=capability.split(".")[0] + "-evidence-v1",
        ),
        observations=tuple(
            Observation(id=i, requirement=r, source_capability=c)
            for i, r, c in observations
        ),
    )


RULE = "每个必考判断及其相关理由均须有效独立通过；不以总分抵消失败。点数仅为主动发起门槛，完整提交沿原轮一次10点，失败不扣分不降级；一次最多晋升一级。待补验只阻止晋升。站内等级是游戏称号，不是职业资历或全知全能证明。"


def _stage(
    points: int,
    before: Level,
    after: Level | None,
    mandatory: tuple[StageJudgment, ...],
) -> BossStage:
    return BossStage(
        version=f"boss-{points}-v1" + ("-challenge" if after is None else ""),
        catalog_version=CATALOG.version,
        from_level=before,
        to_level=after,
        launch_points=points,
        mandatory=mandatory,
        passing_rule=RULE,
    )


PROMOTION_STAGES = (
    _stage(
        300,
        "初级程序员",
        "中级程序员",
        (
            _item(
                "boundary",
                "跨模块边界",
                "architecture.responsibility",
                "进阶",
                (
                    (
                        "ownership",
                        "依据至少两个模块的调用与状态归属，划定责任及跨边界影响。",
                        "architecture.responsibility",
                    ),
                ),
            ),
            _item(
                "consistency",
                "数据一致性",
                "data.integrity",
                "进阶",
                (
                    (
                        "invariant",
                        "根据并发读写和持久约束，判断业务不变量是否在提交边界成立。",
                        "data.integrity",
                    ),
                ),
            ),
            _item(
                "locate",
                "故障定位",
                "network.trace",
                "进阶",
                (
                    (
                        "discriminate",
                        "依据不同链路层的观察定位故障，说明仍需哪条证据区分竞争原因。",
                        "network.trace",
                    ),
                ),
            ),
        ),
    ),
    _stage(
        700,
        "中级程序员",
        "高级程序员",
        (
            _item(
                "concurrency",
                "并发",
                "systems.execution",
                "进阶",
                (
                    (
                        "interleaving",
                        "根据线程或进程的交错时序及共享状态，判断竞争窗口与保护边界。",
                        "systems.execution",
                    ),
                ),
            ),
            _item(
                "authorization",
                "权限安全",
                "security.authorization",
                "进阶",
                (
                    (
                        "owner",
                        "依据身份、资源归属及读写入口，判断越权拒绝必须发生的位置。",
                        "security.authorization",
                    ),
                ),
            ),
            _item(
                "recovery",
                "故障恢复",
                "operations.recovery",
                "进阶",
                (
                    (
                        "restore",
                        "区分程序版本与已变更数据，依据恢复点选择能恢复业务状态的动作。",
                        "operations.recovery",
                    ),
                ),
            ),
            _item(
                "verify",
                "恢复后的验证",
                "testing.coverage",
                "进阶",
                (
                    (
                        "durable",
                        "给出恢复后正常与失败路径的输入、动作、输出和持久结果检查。",
                        "testing.coverage",
                    ),
                ),
            ),
        ),
    ),
    _stage(
        1500,
        "高级程序员",
        "牛逼程序员",
        (
            _item(
                "tradeoff",
                "多约束取舍",
                "requirements.tradeoff",
                "综合",
                (
                    (
                        "constraints",
                        "依据至少两个相互冲突的业务或资源约束比较方案，明确承担的代价和受影响对象。",
                        "requirements.tradeoff",
                    ),
                ),
            ),
            _item(
                "evolution",
                "系统演进",
                "architecture.evolution",
                "综合",
                (
                    (
                        "compatibility",
                        "依据新旧读写协议与迁移过程，判断渐进演进的兼容边界和验证步骤。",
                        "architecture.evolution",
                    ),
                ),
            ),
            _item(
                "containment",
                "故障范围控制",
                "operations.recovery",
                "综合",
                (
                    (
                        "radius",
                        "依据依赖传播及数据变更范围，比较隔离、停止发布和恢复动作的影响范围。",
                        "operations.recovery",
                    ),
                ),
            ),
        ),
    ),
    _stage(
        3000,
        "牛逼程序员",
        "传奇程序员",
        (
            _item(
                "transfer",
                "陌生背景迁移",
                "architecture.evolution",
                "综合",
                (
                    (
                        "context",
                        "新背景中存在与完整已见历史不同的实际因果条件，需重新判断方案适用边界。",
                        "architecture.evolution",
                    ),
                    (
                        "adaptation",
                        "依据当前协议、状态归属和迁移约束，解释原有经验哪些能沿用、哪些须调整。",
                        "architecture.responsibility",
                    ),
                ),
            ),
            _item(
                "counterexample",
                "反例",
                "testing.bias",
                "综合",
                (
                    (
                        "falsify",
                        "用能推翻当前方案假设的故障或依赖反例，区分样本通过与真实风险覆盖。",
                        "testing.bias",
                    ),
                ),
            ),
            _item(
                "review",
                "方案审查",
                "team.review",
                "综合",
                (
                    (
                        "callers",
                        "依据实际调用、验收条件和变更范围，给出有触发证据的风险及最小验证。",
                        "team.review",
                    ),
                ),
            ),
        ),
    ),
    _stage(
        6000,
        "传奇程序员",
        "AI级程序员",
        (
            _item(
                "diagnosis",
                "多领域综合诊断",
                "performance.bottleneck",
                "综合",
                (
                    (
                        "resource",
                        "依据延迟、吞吐和资源或等待指标，判断实际瓶颈而非只凭现象归因。",
                        "performance.bottleneck",
                    ),
                    (
                        "data",
                        "结合持久读写、索引或事务锁的观察，区分数据层与上游等待的因果关系。",
                        "data.query",
                    ),
                    (
                        "queue",
                        "结合异步任务确认、顺序和重试观察，排除或确认队列对端到端故障的作用。",
                        "async.jobs",
                    ),
                ),
            ),
            _item(
                "risk",
                "风险取舍",
                "requirements.tradeoff",
                "综合",
                (
                    (
                        "risk-cost",
                        "比较多个受约束方案的收益、失败代价和受影响对象，说明不可接受的风险边界。",
                        "requirements.tradeoff",
                    ),
                ),
            ),
            _item(
                "verification",
                "验证",
                "testing.coverage",
                "综合",
                (
                    (
                        "verify-result",
                        "针对所选方案明确正常、异常及持久结果的可执行验证步骤和失败判据。",
                        "testing.coverage",
                    ),
                ),
            ),
            _item(
                "rollback",
                "回退",
                "operations.recovery",
                "综合",
                (
                    (
                        "rollback-state",
                        "依据版本、数据变化与恢复点判断回退条件，并说明回退后的业务状态如何核实。",
                        "operations.recovery",
                    ),
                ),
            ),
        ),
    ),
)
AI_CHALLENGE = _stage(6000, "AI级程序员", None, PROMOTION_STAGES[-1].mandatory)
STAGES = (*PROMOTION_STAGES, AI_CHALLENGE)


def next_boss(current_level: str, points: int) -> BossStage | None:
    """High points never select a later stage or skip the current level."""
    if type(points) is not int or points < 0:
        raise ValueError("invalid accumulated points")
    return next(
        (
            s
            for s in STAGES
            if s.from_level == current_level and points >= s.launch_points
        ),
        None,
    )


def validate_stage_mapping(stage: BossStage, case: Candidate) -> None:
    if stage not in STAGES:
        raise ValueError("different frozen Boss standard")
    published = {
        EvidenceKey(
            capability_id=c.id, difficulty=t.difficulty, background_id=c.background_id
        )
        for d in CATALOG.domains
        for c in d.capabilities
        for t in c.levels
    }
    ids = {m.judgment_id for m in stage.mandatory}
    if (
        any(m.target not in published for m in stage.mandatory)
        or case.catalog_version != stage.catalog_version
        or case.target != stage.mandatory[0].target
        or len(case.judgments) != len(ids)
        or {j.id for j in case.judgments} != ids
        or len(case.rubric) != len(ids)
        or {r.judgment_id for r in case.rubric} != ids
    ):
        raise ValueError("incomplete or changed mandatory judgment mapping")


class ObservationCoverage(Strict):
    judgment_id: Text
    observation_id: Text
    requirement_quote: Text
    criterion_quote: Text
    prompt_quote: Text
    reasoning_quote: Text
    evidence_id: Text
    fact: Text
    value: Text
    source_id: Text
    assessment: Literal["matches", "unclear", "mismatch"]
    explanation: Text


def validate_stage_coverage(
    stage: BossStage, case: Candidate, coverage: list[ObservationCoverage]
) -> None:
    """Exact references bind every facet; they do not prove teaching accuracy.

    Full-history novelty is additionally required by assess_mapped_boss. A source
    for a supporting domain is not a passed judgment for that domain.
    """
    validate_stage_mapping(stage, case)
    required = {
        (m.judgment_id, o.id): o for m in stage.mandatory for o in m.observations
    }
    if len(coverage) != len(required) or {
        (c.judgment_id, c.observation_id) for c in coverage
    } != set(required):
        raise ValueError("incomplete Boss observation coverage")
    judgments = {j.id: j for j in case.judgments}
    rubrics = {r.judgment_id: r for r in case.rubric}
    evidence = {e.id: e for e in case.evidence}
    criteria = {c.id: c.criterion for d in CATALOG.domains for c in d.capabilities}
    for claim in coverage:
        required_observation = required[claim.judgment_id, claim.observation_id]
        material = evidence.get(claim.evidence_id)
        if (
            claim.requirement_quote != required_observation.requirement
            or claim.criterion_quote != criteria[required_observation.source_capability]
            or claim.prompt_quote != judgments[claim.judgment_id].prompt
            or claim.reasoning_quote != rubrics[claim.judgment_id].reasoning
            or claim.evidence_id not in judgments[claim.judgment_id].evidence_ids
            or claim.evidence_id not in rubrics[claim.judgment_id].evidence_ids
            or material is None
            or material.facts.get(claim.fact) != claim.value
            or claim.source_id != "boss-" + required_observation.source_capability
            or not any(c.source_id == claim.source_id for c in material.citations)
            or claim.assessment != "matches"
        ):
            raise ValueError("unverified Boss observation coverage")


class StageDecision(Strict):
    outcome: Outcome | Literal["not_admitted", "disputed", "pending_revalidation"]
    promote_to: Level | None = None
    shortfalls: tuple[ConfirmedShortfall, ...] = ()
    semantic_reliability: Literal["unverified"] = "unverified"


def assess_stage(
    *,
    stage: BossStage,
    launch_points: int,
    current_level: str,
    run_id: uuid.UUID,
    mode: Mode,
    freeze_sequence: int,
    case: Candidate,
    sources: list[Source],
    inputs: EvaluationInputs,
    grading_raw: str | None,
    novelty: NoveltyAssessment,
    deliveries: list[OrderedDelivery],
    key: str,
    coverage: list[ObservationCoverage],
    converted_sequence: int | None = None,
    pending_revalidation: bool = False,
    disputed: bool = False,
) -> StageDecision:
    # Admission uses the accepted stage; a late result remains valid after another
    # round promoted. Current level only guards another promotion.
    validate_stage_mapping(stage, case)
    if next_boss(stage.from_level, launch_points) != stage:
        return StageDecision(outcome="not_admitted")
    try:
        validate_stage_coverage(stage, case, coverage)
    except ValueError:
        return StageDecision(outcome="invalid_case")
    result = assess_mapped_boss(
        mandatory=stage.mandatory,
        run_id=run_id,
        mode=mode,
        freeze_sequence=freeze_sequence,
        case=case,
        sources=sources,
        inputs=inputs,
        grading_raw=grading_raw,
        novelty=novelty,
        deliveries=deliveries,
        key=key,
        converted_sequence=converted_sequence,
        disputed=disputed,
    )
    if result.outcome == "independent_pass_candidate":
        assert grading_raw is not None
        grading = validate_grading(grading_raw, case, sources, inputs, key)
        for item in grading.items:
            if not qualified_item(item, coverage):
                # One composite prompt still needs reasons grounded in all its
                # frozen facets; a single source cannot stand in for all domains.
                return StageDecision(outcome="unclear")
    if (
        result.outcome == "independent_pass_candidate"
        and current_level == stage.from_level
        and stage.to_level is not None
    ):
        if pending_revalidation:
            return StageDecision(outcome="pending_revalidation")
        return StageDecision(outcome=result.outcome, promote_to=stage.to_level)
    return StageDecision(outcome=result.outcome, shortfalls=result.shortfalls)


ReleasedStage = FirstStage | BossStage


def stage_at_level(level: str) -> ReleasedStage | None:
    """Display the current standard even before its point threshold is met."""
    if level == FIRST_STAGE.from_level:
        return FIRST_STAGE
    return next((stage for stage in STAGES if stage.from_level == level), None)


def parse_stage(value: dict[str, Any]) -> ReleasedStage:
    raw = json.dumps(value)
    if value.get("version") == FIRST_STAGE.version:
        first = FirstStage.model_validate_json(raw)
        if first != FIRST_STAGE:
            raise ValueError("changed frozen first-stage standard")
        return first
    stage = BossStage.model_validate_json(raw)
    if stage not in STAGES:
        raise ValueError("unknown frozen Boss standard")
    return stage


def qualified_item(item: GradingItem, coverage: list[ObservationCoverage]) -> bool:
    """Call only after validate_grading/validate_stage_coverage on frozen facts.

    The evidence adapter must call this even when another item failed: incomplete
    composite reasoning cannot earn a passed domain merely from a model label.
    """
    if item.conclusion != "pass":
        return False
    required = [c for c in coverage if c.judgment_id == item.judgment_id]
    claimed = {
        (
            item.grounding[c.grounding].evidence_id,
            item.grounding[c.grounding].fact,
            item.grounding[c.grounding].value,
            item.grounding[c.grounding].citation.source_id,
        )
        for c in item.reason_claims
    }
    return bool(required) and all(
        (c.evidence_id, c.fact, c.value, c.source_id) in claimed for c in required
    )
