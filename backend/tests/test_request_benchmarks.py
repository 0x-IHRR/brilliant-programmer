"""Protocol/citation checks only: every semantic label remains pending human review."""

import json
import uuid
from collections import Counter

import pytest
from pydantic import ValidationError

from app.capabilities.catalog import CATALOG
from app.training.evaluation_schema import (
    EvaluationInputs,
    InputSnapshot,
    validate_grading,
)
from app.training.independent_novelty import assess_novelty
from app.training.schema import public_case, validate_candidate
from tests.request_benchmarks import Batch, comparison, load

batch, sources = load()


def test_exact_coverage_no_duplicate_family_or_human_claim():
    cells = Counter(
        (d.candidate.target.capability_id.split(".")[0], d.candidate.target.difficulty)
        for d in batch.cases
    )
    assert set(cells.values()) == {2} and len(cells) == 9
    assert len({d.id for d in batch.cases}) == 18
    assert len({a.id for d in batch.cases for a in d.answers}) == 36
    released = {c.id: c for domain in CATALOG.domains for c in domain.capabilities}
    for d in batch.cases:
        assert (
            released[d.candidate.target.capability_id].background_id
            == d.candidate.target.background_id
        )
        assert d.family == d.candidate.target.capability_id
        assert d.human_review is None
        assert {a.expected_grading.items[0].conclusion for a in d.answers} == {
            "pass",
            "evidenced_fail",
        }
    for field, value in [("review_status", "human_verified"), ("origin", "human")]:
        data = batch.model_dump(mode="json")
        data[field] = value
        with pytest.raises(ValidationError):
            Batch.model_validate_json(json.dumps(data))


@pytest.mark.parametrize("draft", batch.cases, ids=lambda d: d.id)
def test_real_candidate_grading_and_variation_contracts(draft):
    cited = [sources[k] for k in draft.source_ids]
    case = validate_candidate(
        draft.candidate.model_dump_json(),
        draft.candidate.target,
        cited,
        "unused-test-secret",
    )
    variant = validate_candidate(
        draft.positive_variant.model_dump_json(),
        case.target,
        cited,
        "unused-test-secret",
    )
    for label in draft.answers:
        inputs = EvaluationInputs(
            original=InputSnapshot(id=uuid.uuid4(), sequence=1, answers=[label.answer]),
            clarification=None,
            clarification_used=False,
        )
        assert (
            validate_grading(
                label.expected_grading.model_dump_json(),
                case,
                cited,
                inputs,
                "unused-test-secret",
            )
            == label.expected_grading
        )
    seen = uuid.uuid4()
    result = assess_novelty(
        variant,
        cited,
        {seen: case},
        [comparison(case, variant, seen)],
        "unused-test-secret",
    )
    assert (
        result.status == "novelty_candidate"
        and result.semantic_reliability == "unverified"
    )
    renamed = case.model_copy(update={"title": draft.cosmetic_variant.title})
    assert (
        assess_novelty(renamed, cited, {seen: case}, [], "unused-test-secret").status
        == "no_qualified_case"
    )
    assert (
        assess_novelty(variant, cited, {seen: case}, [], "unused-test-secret").status
        == "no_qualified_case"
    )
    public = public_case(case, cited).model_dump()
    assert (
        not {"rubric", "answers", "expected_grading", "positive_variant"}
        & public.keys()
    )
    bad = case.model_dump(mode="json")
    bad["evidence"][0]["citations"][0]["quote"] = (
        "a fabricated quotation that does not exist in the frozen official source"
    )
    with pytest.raises(ValueError):
        validate_candidate(json.dumps(bad), case.target, cited, "unused-test-secret")
