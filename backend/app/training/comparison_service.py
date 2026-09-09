"""Read both immutable legacy snapshots and versioned comparison checkpoints.

These adapters do not call a model or trust a cached assessment alone. Callers
already hold the owner lock and verify the round/evaluation lineage.
"""

import json
import uuid
from typing import Any

from app.training.history_protocol import (
    ComparisonPlan,
    ReferenceResponse,
    assess_plan,
    load_persisted_history,
    restore_history,
)
from app.training.independent_models import IndependentWork
from app.training.independent_novelty import (
    NoveltyAssessment,
    ScenarioComparison,
    assess_novelty,
)
from app.training.schema import Candidate, Source


def frozen_history(work: IndependentWork) -> dict[uuid.UUID, Candidate]:
    if work.history_snapshot is not None:
        return restore_history(load_persisted_history(work.history_snapshot))
    return {
        uuid.UUID(h["run_id"]): Candidate.model_validate_json(h["case"])
        for h in work.history
    }


def qualification(
    work: IndependentWork, case: Candidate, sources: list[Source], key: str
) -> NoveltyAssessment:
    if work.history_snapshot is not None:
        if not work.comparison_plan:
            raise ValueError("missing persisted comparison plan")
        plan = ComparisonPlan.model_validate_json(json.dumps(work.comparison_plan))
        if plan.snapshot != load_persisted_history(work.history_snapshot):
            raise ValueError("different persisted full history")
        if [r.get("batch") for r in work.comparison_results] != list(
            range(len(plan.batches))
        ):
            raise ValueError("incomplete persisted comparison checkpoints")
        return assess_plan(
            plan, case, sources, [r["response"] for r in work.comparison_results], key
        )
    if not work.novelty:
        raise ValueError("missing legacy comparison")
    return assess_novelty(
        case,
        sources,
        frozen_history(work),
        [
            ScenarioComparison.model_validate_json(json.dumps(c))
            for c in work.novelty["comparisons"]["comparisons"]
        ],
        key,
    )


def coverage(work: IndependentWork) -> list[dict[str, Any]]:
    if work.history_snapshot is not None:
        if not work.comparison_results:
            raise ValueError("missing persisted coverage")
        response = ReferenceResponse.model_validate_json(
            work.comparison_results[0]["response"]
        )
        return [c.model_dump(mode="json") for c in response.coverage]
    if not work.novelty:
        raise ValueError("missing legacy coverage")
    values: list[dict[str, Any]] = work.novelty["comparisons"]["boss_coverage"]
    return values
