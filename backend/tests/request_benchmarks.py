"""This batch's reviewable drafts; not a production bank or quality evaluator."""

import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from app.training.evaluation_schema import GradingCandidate
from app.training.independent_novelty import ScenarioComparison
from app.training.schema import Candidate, Source, Strict, Text
from app.training.submission_schema import Answer

DIRECTORY = Path(__file__).resolve().parents[2] / "benchmarks/request-chain"


class Label(Strict):
    id: Text
    answer: Answer
    expected_grading: GradingCandidate
    label_basis: Text
    origin: Literal["ai_draft"]
    review_status: Literal["pending_human_review"]


class Cosmetic(Strict):
    title: Text
    expected: Literal["no_qualified_case"]
    basis: Text


class Help(Strict):
    neutral: Text
    directional: Text
    uncertain: Text


class Draft(Strict):
    id: Text
    family: Text
    origin: Literal["ai_draft"]
    review_status: Literal["pending_human_review"]
    human_review: None
    source_ids: list[Text]
    background_scope: Text
    difficulty_basis: Text
    candidate: Candidate
    answers: list[Label] = Field(min_length=2)
    positive_variant: Candidate
    variation_basis: Text
    cosmetic_variant: Cosmetic
    help: Help


class Batch(Strict):
    version: Literal["request-chain-draft-v0.1"]
    origin: Literal["ai_draft"]
    review_status: Literal["pending_human_review"]
    cases: list[Draft] = Field(min_length=18, max_length=18)


def load() -> tuple[Batch, dict[str, Source]]:
    batch = Batch.model_validate_json((DIRECTORY / "candidates.json").read_text())
    sources = {
        key: Source.model_validate(value)
        for key, value in json.loads((DIRECTORY / "sources.json").read_text()).items()
    }
    return batch, sources


def comparison(before: Candidate, after: Candidate, seen_id) -> ScenarioComparison:
    """A controlled model reply bound to this draft's actual changed observation."""
    return ScenarioComparison(
        seen_run_id=seen_id,
        seen_judgment_id=before.judgments[0].id,
        new_judgment_id=after.judgments[0].id,
        relation="different_causal_scenario",
        changes=[
            {
                "dimension": "causal_condition",
                "before": {
                    "evidence_id": "observation",
                    "fact": "observed_boundary",
                    "value": before.evidence[0].facts["observed_boundary"],
                },
                "after": {
                    "evidence_id": "observation",
                    "fact": "observed_boundary",
                    "value": after.evidence[0].facts["observed_boundary"],
                },
                "before_variation": before.variation.causal_condition,
                "after_variation": after.variation.causal_condition,
                "before_reasoning": before.rubric[0].reasoning,
                "after_reasoning": after.rubric[0].reasoning,
                "before_consequence": before.judgments[0].options[0],
                "after_consequence": after.judgments[0].options[0],
                "effect": "different_decision",
                "explanation": after.rubric[0].reasoning,
            }
        ],
    )
