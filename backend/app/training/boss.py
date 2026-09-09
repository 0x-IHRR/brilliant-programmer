"""First-stage proposals over frozen server facts; no level/point/evidence writes.

Display/persist FIRST_STAGE before generation; bind mandatory IDs before answering.
Settlement must hold the owner lock and bind original/evaluation/rule snapshots,
with a unique promotion identity. This is not a public request payload.
"""

import uuid
from typing import Literal

from app.capabilities.catalog import CATALOG, EvidenceKey
from app.training.evaluation_schema import EvaluationInputs, validate_grading
from app.training.independent import Mode, OrderedDelivery, Outcome, frozen_outcome
from app.training.independent_novelty import NoveltyAssessment
from app.training.schema import Candidate, Source, Strict, Text


class MandatoryJudgment(Strict):
    judgment_id: Text
    scope: Literal["请求／状态链路", "局部因果", "查证与验证"]
    target: EvidenceKey


class FirstStage(Strict):
    version: Literal["first-boss-v1"] = "first-boss-v1"
    catalog_version: str
    from_level: Literal["小白程序员"] = "小白程序员"
    to_level: Literal["初级程序员"] = "初级程序员"
    launch_points: Literal[100] = 100
    mandatory: tuple[MandatoryJudgment, MandatoryJudgment, MandatoryJudgment]
    passing_rule: str


# Concrete release backgrounds, not a claim to cover every background. No answers.
FIRST_STAGE = FirstStage(
    catalog_version=CATALOG.version,
    mandatory=(
        MandatoryJudgment(
            judgment_id="boss-chain",
            scope="请求／状态链路",
            target=EvidenceKey(
                capability_id="network.trace",
                difficulty="基础",
                background_id="network-evidence-v1",
            ),
        ),
        MandatoryJudgment(
            judgment_id="boss-cause",
            scope="局部因果",
            target=EvidenceKey(
                capability_id="frontend.state",
                difficulty="基础",
                background_id="frontend-evidence-v1",
            ),
        ),
        MandatoryJudgment(
            judgment_id="boss-verify",
            scope="查证与验证",
            target=EvidenceKey(
                capability_id="testing.coverage",
                difficulty="基础",
                background_id="testing-evidence-v1",
            ),
        ),
    ),
    passing_rule="三个必考判断及简短理由均须获得有效独立通过；不以总分抵消失败。100点仅为主动发起门槛，无需刷完所有小关；完整提交沿原轮一次10点，失败不扣分不降级。",
)


def can_launch_first_boss(points: int, current_level: str) -> bool:
    if type(points) is not int or points < 0:
        raise ValueError("invalid accumulated points")
    return (
        points >= FIRST_STAGE.launch_points and current_level == FIRST_STAGE.from_level
    )


def validate_boss_mapping(stage: FirstStage, case: Candidate) -> None:
    """ID binding is not semantic coverage: prompts/rubrics still need inspection.

    Single primary target is the existing Candidate carrier, not three proofs.
    """
    if stage != FIRST_STAGE:
        raise ValueError("different frozen first-stage standard")
    published = {
        EvidenceKey(
            capability_id=c.id, difficulty=t.difficulty, background_id=c.background_id
        )
        for d in CATALOG.domains
        for c in d.capabilities
        for t in c.levels
    }
    if any(item.target not in published for item in stage.mandatory):
        raise ValueError("unpublished mandatory target")
    ids = {item.judgment_id for item in stage.mandatory}
    if (
        case.catalog_version != stage.catalog_version
        or case.target != stage.mandatory[0].target
        or len(case.judgments) != len(ids)
        or {j.id for j in case.judgments} != ids
        or len(case.rubric) != len(ids)
        or {r.judgment_id for r in case.rubric} != ids
    ):
        raise ValueError("incomplete or changed mandatory judgment mapping")


class ConfirmedShortfall(Strict):
    judgment_id: Text
    target: EvidenceKey
    gap: Text


class BossDecision(Strict):
    outcome: Outcome | Literal["not_admitted", "disputed", "pending_revalidation"]
    promote_to: Literal["初级程序员"] | None = None
    shortfalls: tuple[ConfirmedShortfall, ...] = ()
    semantic_reliability: Literal["unverified"] = "unverified"


def assess_first_boss(
    *,
    stage: FirstStage,
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
    converted_sequence: int | None = None,
    pending_revalidation: bool = False,
    disputed: bool = False,
) -> BossDecision:
    """Use launch-time points, excluding this submission's +10.

    Re-read current level under settlement lock: a completed promotion cannot jump
    again. R074 shortfalls also apply to unverified targets; emit only failed mapped
    items, not whole-case outcomes for every target or invented original IDs/orders.
    """
    if not can_launch_first_boss(launch_points, current_level):
        return BossDecision(outcome="not_admitted")
    validate_boss_mapping(stage, case)
    if disputed:
        return BossDecision(outcome="disputed")
    outcome = frozen_outcome(
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
    )
    if outcome == "independent_pass_candidate":
        if pending_revalidation:
            return BossDecision(outcome="pending_revalidation")
        return BossDecision(outcome=outcome, promote_to=stage.to_level)
    if outcome != "evidenced_fail":
        return BossDecision(outcome=outcome)
    assert grading_raw is not None
    grading = validate_grading(grading_raw, case, sources, inputs, key)
    by_id = {item.judgment_id: item for item in grading.items}
    gaps = []
    for item in stage.mandatory:
        grade = by_id[item.judgment_id]
        if grade.conclusion == "evidenced_fail" and grade.gap is not None:
            gaps.append(
                ConfirmedShortfall(
                    judgment_id=item.judgment_id, target=item.target, gap=grade.gap
                )
            )
    return BossDecision(outcome=outcome, shortfalls=tuple(gaps))
