"""Private guidance drafts and same-scenario practice; no publication or settlement.

Callers must resolve ownership and actual demonstration delivery before exposing a
practice or these drafts. Shared delivery inspection/receipts and the existing
round award transaction remain the only publication/settlement boundaries.
"""

from typing import Literal

from pydantic import Field

from app.model_config.output import check_output
from app.training.schema import (
    Candidate,
    Judgment,
    PublicCase,
    PublicEvidence,
    Source,
    Strict,
    Text,
    public_case,
    scenario_fingerprint,
    validate_candidate,
)
from app.training.submission_schema import Answer, Relevance, validate_answers


class WorkedAnswer(Strict):
    acceptable_values: list[int | list[int] | Text] = Field(min_length=1, max_length=6)
    reasoning: Text
    counterexample: Text


class GuidanceStep(Strict):
    judgment: Judgment
    evidence: list[PublicEvidence] = Field(min_length=1, max_length=12)
    solution: WorkedAnswer | None = None


class GuidanceDraft(Strict):
    kind: Literal["hint", "demonstration"]
    scenario_fingerprint: str
    steps: list[GuidanceStep] = Field(min_length=1, max_length=4)
    # Both variants point to the actual judgment's selected evidence. This is
    # directional by construction, not a neutrality claim based on the button.
    direction: Literal["directional"] = "directional"


def checked_case(candidate: Candidate, sources: list[Source], key: str) -> Candidate:
    return validate_candidate(
        candidate.model_dump_json(), candidate.target, sources, key
    )


def guidance_draft(
    candidate: Candidate,
    sources: list[Source],
    kind: Literal["hint", "demonstration"],
    key: str,
) -> GuidanceDraft:
    """Reuse frozen answers; the result is PRIVATE pending safe explicit delivery.

    This is not another model-generated answer or an assertion of teaching quality.
    Inspection of the actual prose still precedes publication, including unsafe
    instructions that may occur in source material or an existing rubric.
    """
    candidate = checked_case(candidate, sources, key)
    visible = public_case(candidate, sources)
    evidence = {item.id: item for item in visible.evidence}
    rubric = {item.judgment_id: item for item in candidate.rubric}
    steps = []
    for judgment in candidate.judgments:
        rule = rubric[judgment.id]
        solution = None
        if kind == "demonstration":
            values: list[int | list[int] | str] = [
                *rule.acceptable_options,
                *rule.acceptable_orders,
                *rule.acceptable_predictions,
            ]
            solution = WorkedAnswer(
                acceptable_values=values,
                reasoning=rule.reasoning,
                counterexample=rule.counterexample,
            )
        steps.append(
            GuidanceStep(
                judgment=judgment,
                evidence=[
                    evidence[identity] for identity in dict.fromkeys(rule.evidence_ids)
                ],
                solution=solution,
            )
        )
    draft = GuidanceDraft(
        kind=kind,
        scenario_fingerprint=scenario_fingerprint(candidate),
        steps=steps,
    )
    check_output(draft.model_dump_json(), key)
    return draft


class PracticeCase(Strict):
    kind: Literal["same_scenario_practice"] = "same_scenario_practice"
    scenario_fingerprint: str
    case: PublicCase
    instructions: str = (
        "这是已看示范的同一情境小练习。请自己填写判断和一句相关理由；"
        "可以用白话说还需查什么，不要求答对。不会作为陌生题独立检验。"
    )


def exercise_candidate(candidate: Candidate, judgment_id: str) -> Candidate:
    """Select one frozen judgment for a small exercise, preserving scenario identity."""
    judgments = [item for item in candidate.judgments if item.id == judgment_id]
    if len(judgments) != 1:
        raise ValueError("unknown practice judgment")
    return candidate.model_copy(
        update={
            "judgments": judgments,
            "rubric": [
                item for item in candidate.rubric if item.judgment_id == judgment_id
            ],
        },
        deep=True,
    )


def practice_case(
    candidate: Candidate, sources: list[Source], judgment_id: str, key: str
) -> PracticeCase:
    """No new facts, new scenario identity, prefilled answers or hidden rubric.

    The selected exercise has its own completion fact. It never marks an incomplete
    original submission complete. The owned route enforces demonstration delivery;
    both paths share the original run's single award, not separate round identities.
    """
    candidate = checked_case(candidate, sources, key)
    result = PracticeCase(
        scenario_fingerprint=scenario_fingerprint(candidate),
        case=public_case(exercise_candidate(candidate, judgment_id), sources),
    )
    check_output(result.model_dump_json(), key)
    return result


def practice_completion(
    candidate: Candidate, answers: list[Answer], relevance: Relevance
) -> Literal["completed", "needs_supplement"]:
    """Completion checks relevance, never correctness; does not award or grade.

    Relevance is the server's model result, not an accepted client assertion. A
    missing, duplicated or foreign judgment cannot vacuously complete the round.
    """
    validate_answers(candidate, answers)
    expected = {judgment.id for judgment in candidate.judgments}
    if (
        len(relevance.items) != len(expected)
        or {item.judgment_id for item in relevance.items} != expected
    ):
        raise ValueError("incomplete practice relevance")
    return (
        "completed"
        if all(item.status == "related" for item in relevance.items)
        else "needs_supplement"
    )
