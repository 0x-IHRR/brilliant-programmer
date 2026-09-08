"""Evidence-linked grading candidates; semantic interpretation remains model-dependent."""

import uuid
from typing import Literal

from pydantic import Field

from app.training.schema import Candidate, Citation, Source, Strict, Text
from app.training.submission_models import Submission
from app.training.submission_schema import Answer, validate_answers

EVALUATION_RULE = "evidence-feedback-v1.0"
NEUTRAL_QUESTION = "请用自己的话补充原答的意思和依据，或说明哪些地方还不能确定。可以结束澄清；不会因此记为有据失败。"


class InputSnapshot(Strict):
    id: uuid.UUID
    sequence: int
    answers: list[Answer] = Field(min_length=1, max_length=4)


class EvaluationInputs(Strict):
    original: InputSnapshot
    clarification: InputSnapshot | None = None
    clarification_used: bool


def evaluation_inputs(submissions: list[Submission]) -> EvaluationInputs:
    """Supplements never become original evidence, even if they earned completion."""
    originals = [s for s in submissions if s.kind == "original"]
    clarifications = [s for s in submissions if s.kind == "clarification"]
    if (
        len(originals) != 1
        or len(clarifications) > 1
        or len({s.run_id for s in submissions}) != 1
        or len({s.id for s in submissions}) != len(submissions)
    ):
        raise ValueError("invalid evaluation lineage")
    original = originals[0]
    clarification = clarifications[0] if clarifications else None
    if original.original_id is not None or original.sequence is None:
        raise ValueError("invalid original identity")
    if clarification and (
        clarification.original_id != original.id
        or clarification.sequence is None
        or clarification.sequence <= original.sequence
        or not any(
            s.neutral_clarification
            and s.sequence is not None
            and s.sequence < clarification.sequence
            for s in submissions
        )
    ):
        raise ValueError("unpermitted clarification")

    def snapshot(submission: Submission) -> InputSnapshot:
        assert submission.sequence is not None
        return InputSnapshot(
            id=submission.id,
            sequence=submission.sequence,
            answers=[Answer.model_validate(a) for a in submission.answers],
        )

    return EvaluationInputs(
        original=snapshot(original),
        clarification=snapshot(clarification) if clarification else None,
        clarification_used=bool(clarification)
        or any(s.neutral_clarification for s in submissions),
    )


class AnswerQuote(Strict):
    input: Literal["original", "clarification"]
    field: Literal["value", "reason"]
    quote: Text


class Grounding(Strict):
    evidence_id: Text
    fact: Text
    value: Text
    citation: Citation


class ReasonClaim(Strict):
    # References the full reason and a separately verified frozen fact.
    answer_quote: int = Field(ge=0, le=7)
    grounding: int = Field(ge=0, le=11)
    interpreted_fact_value: Text


class GradingItem(Strict):
    judgment_id: Text
    conclusion: Literal["pass", "evidenced_fail", "unclear"]
    answer_quotes: list[AnswerQuote] = Field(min_length=1, max_length=8)
    grounding: list[Grounding] = Field(max_length=12)
    # Meaning is a candidate interpretation, not a keyword score or confidence.
    interpreted_value: int | list[int] | Text | None
    interpreted_reasoning: int | list[int] | Text | None
    reason_claims: list[ReasonClaim] = Field(max_length=12)
    rule_quote: Text | None
    counterexample_quote: Text | None
    explanation: Text
    gap: Text | None


class GradingCandidate(Strict):
    items: list[GradingItem] = Field(min_length=1, max_length=4)


def validate_grading(
    raw: str,
    case: Candidate,
    sources: list[Source],
    inputs: EvaluationInputs,
    key: str,
) -> GradingCandidate:
    """Check witnesses and rule applicability, never accept a bare model verdict.

    The model still interprets natural language. This check does not certify that
    interpretation: #35–40's labelled quality gate remains separately required.
    """
    if key and key in raw:
        raise ValueError("secret echoed")
    result = GradingCandidate.model_validate_json(raw)
    judgments = {j.id: j for j in case.judgments}
    if len(result.items) != len(judgments) or {
        item.judgment_id for item in result.items
    } != set(judgments):
        raise ValueError("incomplete grading")
    validate_answers(case, inputs.original.answers)
    if inputs.clarification:
        validate_answers(case, inputs.clarification.answers)
    evidence = {e.id: e for e in case.evidence}
    source_by_id = {s.id: s for s in sources}
    rubrics = {r.judgment_id: r for r in case.rubric}
    for item in result.items:
        judgment = judgments[item.judgment_id]
        rubric = rubrics[item.judgment_id]
        used_inputs = set()
        for quote in item.answer_quotes:
            snapshot = getattr(inputs, quote.input)
            if snapshot is None:
                raise ValueError("unavailable answer cited")
            answer = next(a for a in snapshot.answers if a.judgment_id == judgment.id)
            value = getattr(answer, quote.field)
            if not isinstance(value, str) or quote.quote != value:
                raise ValueError("fabricated answer quotation")
            used_inputs.add(quote.input)
        if "original" not in used_inputs:
            raise ValueError("original answer omitted")
        if inputs.clarification and "clarification" not in used_inputs:
            raise ValueError("permitted clarification omitted")
        if not any(quote.field == "reason" for quote in item.answer_quotes):
            raise ValueError("reasoning omitted")
        for witness in item.grounding:
            material = evidence.get(witness.evidence_id)
            source = source_by_id.get(witness.citation.source_id)
            if (
                witness.evidence_id not in rubric.evidence_ids
                or material is None
                or material.facts.get(witness.fact) != witness.value
                or witness.citation not in material.citations
                or source is None
                or witness.citation.quote not in source.text
            ):
                raise ValueError("unsupported grading fact")
        if item.rule_quote is not None and item.rule_quote != rubric.reasoning:
            raise ValueError("different frozen rule")
        if (
            item.counterexample_quote is not None
            and item.counterexample_quote != rubric.counterexample
        ):
            raise ValueError("different frozen counterexample")
        fact_conflict = False
        fact_unknown = False
        for claim in item.reason_claims:
            if (
                claim.answer_quote >= len(item.answer_quotes)
                or claim.grounding >= len(item.grounding)
                or item.answer_quotes[claim.answer_quote].field != "reason"
            ):
                raise ValueError("unlinked reasoning claim")
            actual = item.grounding[claim.grounding].value
            if claim.interpreted_fact_value != actual:
                # Only opposite canonical booleans establish contradiction here;
                # unequal free text may be synonyms, not contradictory facts.
                if {actual, claim.interpreted_fact_value} == {"true", "false"}:
                    fact_conflict = True
                else:
                    fact_unknown = True
        if item.conclusion == "unclear":
            if not item.gap:
                raise ValueError("missing uncertainty")
            continue
        if (
            not item.grounding
            or not item.reason_claims
            or item.interpreted_reasoning is None
            or item.rule_quote is None
            or fact_unknown
        ):
            raise ValueError("unwitnessed conclusion")
        answer = next(
            a
            for a in (inputs.clarification or inputs.original).answers
            if a.judgment_id == judgment.id
        )
        if judgment.kind != "prediction" and item.interpreted_value != answer.value:
            raise ValueError("changed submitted decision")
        if judgment.kind == "prediction" and not isinstance(
            item.interpreted_value, str
        ):
            raise ValueError("missing interpreted prediction")
        # Reuse the answer boundary: invented choice IDs or incomplete orderings
        # are not valid interpretations of the reason either.
        validate_answers(
            case,
            [
                a.model_copy(update={"value": item.interpreted_reasoning})
                if a.judgment_id == judgment.id
                else a
                for a in (inputs.clarification or inputs.original).answers
            ],
        )
        acceptable = (
            rubric.acceptable_options
            if judgment.kind == "choice"
            else rubric.acceptable_orders
            if judgment.kind == "order"
            else rubric.acceptable_predictions
        )
        decision_supported = item.interpreted_value in acceptable
        reasoning_supported = item.interpreted_reasoning in acceptable
        if item.conclusion == "pass" and (
            not decision_supported
            or not reasoning_supported
            or fact_conflict
            or item.gap is not None
        ):
            raise ValueError("unsupported pass or invented gap")
        if item.conclusion == "evidenced_fail" and (
            (decision_supported and reasoning_supported and not fact_conflict)
            or (not fact_conflict and item.counterexample_quote is None)
            or not item.gap
        ):
            raise ValueError("unsupported failure")
    return result
