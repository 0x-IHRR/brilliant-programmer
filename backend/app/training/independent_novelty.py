"""Evidence-bound novelty candidates, not certified semantic novelty.

The caller supplies the complete seen-scenario history (including other sessions
and later explanations) and separately reconciles unknown exposures. Comparisons
are model interpretations checked against frozen data. Passing these mechanical
checks does not prove that a claimed causal effect is true: labelled paraphrase /
causal-variant samples are still required by the semantic quality gate (#35–40).
No model-provided is_new flag, new ID or fingerprint grants eligibility.
"""

import hashlib
import json
import uuid
from typing import Literal

from pydantic import Field

from app.model_config.output import check_output
from app.training.schema import (
    Candidate,
    Rubric,
    Source,
    Strict,
    Text,
    validate_candidate,
)


class FactReference(Strict):
    evidence_id: Text
    fact: Text
    value: Text


class ScenarioChange(Strict):
    dimension: Literal["causal_condition", "expected_evidence", "decision_effect"]
    before: FactReference
    after: FactReference
    # Exact frozen variation and judgment-rule text anchor the interpretation.
    before_variation: Text
    after_variation: Text
    before_reasoning: Text
    after_reasoning: Text
    # These describe why the changed fact changes the judgment, not just wording.
    before_consequence: Text
    after_consequence: Text
    effect: Literal["different_decision", "different_required_evidence"]
    explanation: Text


class ScenarioComparison(Strict):
    seen_run_id: uuid.UUID
    seen_judgment_id: Text
    new_judgment_id: Text
    relation: Literal["same_scenario", "different_causal_scenario", "unclear"]
    changes: list[ScenarioChange] = Field(max_length=12)


class NoveltyAssessment(Strict):
    status: Literal["novelty_candidate", "no_qualified_case"]
    reason: str
    case_digest: str
    semantic_reliability: Literal["unverified"] = "unverified"


def case_digest(case: Candidate) -> str:
    """Identity binding only; this digest is never proof of semantic novelty."""
    return hashlib.sha256(case.model_dump_json().encode()).hexdigest()


def _decisions(case: Candidate, rule: Rubric) -> set[str]:
    judgment = next(j for j in case.judgments if j.id == rule.judgment_id)
    if judgment.kind == "choice":
        return {judgment.options[i] for i in rule.acceptable_options}
    if judgment.kind == "order":
        return {
            json.dumps([judgment.options[i] for i in order], ensure_ascii=False)
            for order in rule.acceptable_orders
        }
    return set(rule.acceptable_predictions)


def _facts(case: Candidate, rule: Rubric) -> set[tuple[str, str]]:
    return {
        (name, value)
        for evidence in case.evidence
        if evidence.id in rule.evidence_ids
        for name, value in evidence.facts.items()
    }


def _fact_matches(case: Candidate, rule: Rubric, ref: FactReference) -> bool:
    return any(
        e.id == ref.evidence_id
        and e.id in rule.evidence_ids
        and e.facts.get(ref.fact) == ref.value
        for e in case.evidence
    )


def _bound_change(
    old: Candidate,
    new: Candidate,
    before: Rubric,
    after: Rubric,
    change: ScenarioChange,
) -> bool:
    if not (
        _fact_matches(old, before, change.before)
        and _fact_matches(new, after, change.after)
        and change.before_variation == getattr(old.variation, change.dimension)
        and change.after_variation == getattr(new.variation, change.dimension)
        and change.before_reasoning == before.reasoning
        and change.after_reasoning == after.reasoning
    ):
        return False
    if change.effect == "different_decision":
        # Option indices are identities, not meanings. Reordering options is not
        # a changed decision, nor is selecting two existing valid alternatives.
        old_decisions, new_decisions = _decisions(old, before), _decisions(new, after)
        return (
            change.before_consequence in old_decisions - new_decisions
            and change.after_consequence in new_decisions - old_decisions
            and (
                change.before.value != change.after.value
                or change.dimension == "decision_effect"
            )
        )
    # Same conclusion may require different evidence. Preserve this legitimate
    # variant instead of requiring every answer or structure to change.
    return (
        change.before.value != change.after.value
        and change.before_consequence == old.variation.expected_evidence
        and change.after_consequence == new.variation.expected_evidence
        and change.before_consequence != change.after_consequence
        and before.reasoning != after.reasoning
    )


def assess_novelty(
    new: Candidate,
    sources: list[Source],
    seen: dict[uuid.UUID, Candidate],
    comparisons: list[ScenarioComparison],
    key: str,
) -> NoveltyAssessment:
    """Check the new case and every old/new judgment pair, fail closed on gaps.

    Seen cases are already validated frozen cases; they must not be replaced by
    current model summaries. Return an explicit exit when no candidate qualifies.
    Never serialize comparisons (which include private rules) in an ordinary API.
    """
    validate_candidate(new.model_dump_json(), new.target, sources, key)
    check_output(json.dumps([c.model_dump(mode="json") for c in comparisons]), key)

    def no(reason: str) -> NoveltyAssessment:
        return NoveltyAssessment(
            status="no_qualified_case", reason=reason, case_digest=case_digest(new)
        )

    for old in seen.values():
        for before in old.rubric:
            for after in new.rubric:
                if (
                    _facts(old, before) == _facts(new, after)
                    and before.reasoning == after.reasoning
                    and _decisions(old, before) == _decisions(new, after)
                ):
                    return no("unchanged_judgment_facts")
    required = {
        (run_id, old.id, fresh.id)
        for run_id, case in seen.items()
        for old in case.judgments
        for fresh in new.judgments
    }
    actual = {
        (c.seen_run_id, c.seen_judgment_id, c.new_judgment_id) for c in comparisons
    }
    if len(actual) != len(comparisons) or actual != required:
        return no("incomplete_comparison")
    for comparison in comparisons:
        if comparison.relation != "different_causal_scenario":
            return no(comparison.relation)
        old = seen[comparison.seen_run_id]
        before = next(
            r for r in old.rubric if r.judgment_id == comparison.seen_judgment_id
        )
        after = next(
            r for r in new.rubric if r.judgment_id == comparison.new_judgment_id
        )
        if not comparison.changes or not all(
            _bound_change(old, new, before, after, change)
            for change in comparison.changes
        ):
            return no("unbound_or_cosmetic_change")
    return NoveltyAssessment(
        status="novelty_candidate",
        reason="comparisons_bound",
        case_digest=case_digest(new),
    )
