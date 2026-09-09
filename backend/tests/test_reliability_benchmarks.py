"""Structural witnesses never certify the AI-drafted labels as human truth."""

import json
import uuid
from collections import Counter

import pytest
from pydantic import ValidationError

from app.training.evaluation_schema import (
    EvaluationInputs,
    InputSnapshot,
    validate_grading,
)
from app.training.independent_novelty import assess_novelty
from app.training.schema import validate_candidate
from app.training.submission_schema import validate_answers
from tests.reliability_benchmarks import Batch, comparison, load

batch, sources = load()

# Per-case editorial source binding, not an automated semantic quality verdict.
PRIMARY = {
    "testing.coverage-1": ("playwright", 0, 0),
    "testing.coverage-2": ("playwright", 2, 2),
    "testing.coverage-3": ("playwright", 1, 1),
    "testing.bias-1": ("pitfalls", 0, 0),
    "testing.bias-2": ("pitfalls", 1, 0),
    "testing.bias-3": ("cross", 0, 1),
    "performance.bottleneck-1": ("monitoring", 1, 2),
    "performance.bottleneck-2": ("monitoring", 0, 0),
    "performance.bottleneck-3": ("monitoring", 2, 1),
    "performance.capacity-1": ("overload", 0, 0),
    "performance.capacity-2": ("overload", 1, 1),
    "performance.capacity-3": ("overload", 2, 2),
    "operations.configuration-1": ("compose", 1, 2),
    "operations.configuration-2": ("probes", 0, 1),
    "operations.configuration-3": ("probes", 2, 1),
    "operations.recovery-1": ("deployment", 0, 0),
    "operations.recovery-2": ("pitr", 0, 2),
    "operations.recovery-3": ("pitr", 1, 1),
}


@pytest.mark.parametrize("draft", batch.cases, ids=lambda d: d.id)
def test_production_contracts_and_actual_variation(draft):
    refs = [sources[k] for k in draft.source_ids]
    source_id, base_quote, variant_quote = PRIMARY[draft.id]
    for case, quote_index in [
        (draft.candidate, base_quote),
        (draft.positive_variant, variant_quote),
    ]:
        citation = case.evidence[0].citations[0]
        assert citation.source_id == source_id
        assert citation.quote == sources[source_id].text.split("\n[…]\n")[quote_index]
    for case in [draft.candidate, draft.positive_variant]:
        assert (
            validate_candidate(
                case.model_dump_json(), case.target, refs, "controlled-secret-only"
            )
            == case
        )
        for evidence in case.evidence:
            for citation in evidence.citations:
                assert citation.quote in sources[citation.source_id].text
    for label in draft.answers:
        validate_answers(draft.candidate, [label.answer])
        inputs = EvaluationInputs(
            original=InputSnapshot(id=uuid.uuid4(), sequence=1, answers=[label.answer]),
            clarification=None,
            clarification_used=False,
        )
        validate_grading(
            label.expected_grading.model_dump_json(),
            draft.candidate,
            refs,
            inputs,
            "controlled-secret-only",
        )
    assert {a.expected_grading.items[0].conclusion for a in draft.answers} == {
        "pass",
        "evidenced_fail",
    }
    seen_id = uuid.uuid4()
    result = assess_novelty(
        draft.positive_variant,
        refs,
        {seen_id: draft.candidate},
        [comparison(draft, seen_id)],
        "controlled-secret-only",
    )
    assert (
        result.status == "novelty_candidate"
        and result.semantic_reliability == "unverified"
    )
    renamed = draft.candidate.model_copy(update={"title": draft.cosmetic_title})
    assert (
        assess_novelty(
            renamed, refs, {seen_id: draft.candidate}, [], "controlled-secret-only"
        ).status
        == "no_qualified_case"
    )


def test_matrix_and_machine_pending_status():
    expected = {
        f"{family}-{tier}"
        for family in [
            "testing.coverage",
            "testing.bias",
            "performance.bottleneck",
            "performance.capacity",
            "operations.configuration",
            "operations.recovery",
        ]
        for tier in [1, 2, 3]
    }
    assert {d.id for d in batch.cases} == expected
    assert len(batch.cases) == 18 and sum(len(d.answers) for d in batch.cases) == 36
    assert Counter(
        (d.candidate.target.capability_id.split(".")[0], d.candidate.target.difficulty)
        for d in batch.cases
    ) == Counter(
        {
            (domain, tier): 2
            for domain in ["testing", "performance", "operations"]
            for tier in ["基础", "进阶", "综合"]
        }
    )
    value = json.loads(batch.model_dump_json())
    value["cases"][0]["answers"][0]["review_status"] = "human_approved"
    with pytest.raises(ValidationError):
        Batch.model_validate(value)
    value = json.loads(batch.model_dump_json())
    value["cases"][0]["human_review"] = {"reviewer": "invented"}
    with pytest.raises(ValidationError):
        Batch.model_validate(value)
