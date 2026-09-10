"""This batch's review envelope; production owns candidate/grading semantics."""

import json
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.training.evaluation_schema import GradingCandidate
from app.training.independent_novelty import ScenarioComparison
from app.training.schema import Candidate, Source
from app.training.submission_schema import Answer

ROOT = Path(__file__).resolve().parents[2] / "benchmarks/service-data"


class Pending(BaseModel):
    model_config = ConfigDict(extra="forbid")
    origin: Literal["ai_draft"]
    review_status: Literal["pending_human_review"]


class Label(Pending):
    answer: Answer
    expected_grading: GradingCandidate
    label_basis: str


class Help(BaseModel):
    model_config = ConfigDict(extra="forbid")
    neutral: str
    directional: str
    uncertain: str


class Draft(Pending):
    id: str
    family: str
    human_review: None
    source_ids: list[str]
    candidate: Candidate
    answers: list[Label]
    positive_variant: Candidate
    cosmetic_title: str
    variation_basis: str
    help: Help


class Batch(Pending):
    cases: list[Draft]


def load():
    batch = Batch.model_validate_json((ROOT / "candidates.json").read_text())
    sources = {
        k: Source.model_validate(v)
        for k, v in json.loads((ROOT / "sources.json").read_text()).items()
    }
    return batch, sources


def comparison(draft: Draft, seen_id: uuid.UUID) -> ScenarioComparison:
    old, new = draft.candidate, draft.positive_variant
    return ScenarioComparison.model_validate(
        {
            "seen_run_id": seen_id,
            "seen_judgment_id": "j1",
            "new_judgment_id": "j1",
            "relation": "different_causal_scenario",
            "changes": [
                {
                    "dimension": "causal_condition",
                    "before": {
                        "evidence_id": "e1",
                        "fact": "observed_boundary",
                        "value": old.evidence[0].facts["observed_boundary"],
                    },
                    "after": {
                        "evidence_id": "e1",
                        "fact": "observed_boundary",
                        "value": new.evidence[0].facts["observed_boundary"],
                    },
                    "before_variation": old.variation.causal_condition,
                    "after_variation": new.variation.causal_condition,
                    "before_reasoning": old.rubric[0].reasoning,
                    "after_reasoning": new.rubric[0].reasoning,
                    "before_consequence": old.judgments[0].options[0],
                    "after_consequence": new.judgments[0].options[0],
                    "effect": "different_decision",
                    "explanation": draft.variation_basis,
                }
            ],
        }
    )
