"""Seed-replayable random selection from server evidence and published access.

Availability here means an eligible published target, not a claim that model
output is already a qualified case. Actual source/case gates still run later.
"""

import random
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel

from app.capabilities.catalog import EvidenceKey
from app.capabilities.evidence import EvidenceMap
from app.capabilities.unlocks import UnitAccess

Preference = Literal["recommended", "基础", "进阶", "综合"]
RULE = "random-recommendation-v1"
ORDER = {"基础": 0, "进阶": 1, "综合": 2}


class Selection(BaseModel):
    target: EvidenceKey | None
    candidates: list[EvidenceKey]
    reason: str
    excluded: list[dict[str, str]]


def choose(
    *,
    units: list[UnitAccess],
    evidence: EvidenceMap,
    preference: Preference,
    has_record: bool,
    delivered: int,
    now: datetime,
    seed: str,
    previous_capability: str | None = None,
) -> Selection:
    states = {s.target: s for s in evidence.states}
    available = []
    excluded = []
    for unit in units:
        why = None
        if not unit.eligible:
            why = "missing_prerequisites"
        elif previous_capability == unit.target.capability_id:
            why = "requested_other_direction"
        elif not has_record and (
            unit.target.difficulty != "基础"
            or unit.missing_required
            or unit.missing_alternatives
        ):
            why = "first_basic_without_prerequisites"
        elif (
            has_record
            and preference != "recommended"
            and unit.target.difficulty != preference
        ):
            why = "fixed_difficulty"
        if why:
            excluded.append({**unit.target.model_dump(), "reason": why})
        else:
            available.append(unit.target)

    def state(key: EvidenceKey) -> str:
        return states[key].status if key in states else "unverified"

    def verified_at(key: EvidenceKey) -> datetime | None:
        return states[key].latest_verified_at if key in states else None

    def key_order(key: EvidenceKey) -> tuple[str, str, int]:
        return key.capability_id, key.background_id, ORDER[key.difficulty]

    available.sort(key=key_order)
    pool = []
    reason = "first_basic"
    if not has_record:
        pool = available
    else:
        grouped: dict[tuple[str, str], list[EvidenceKey]] = {}
        for key in available:
            grouped.setdefault((key.capability_id, key.background_id), []).append(key)
        review = preference == "recommended" and (delivered + 1) % 5 == 0
        if review:
            for keys in grouped.values():
                old = [
                    k
                    for k in keys
                    if state(k) == "verified"
                    and (when := verified_at(k)) is not None
                    and now - when >= timedelta(days=7)
                ]
                if old:
                    pool.append(min(old, key=lambda k: (verified_at(k), key_order(k))))
            reason = "seventh_day_review"
        if not pool:
            for wanted in ("needs_consolidation", "unverified", "verified"):
                for keys in grouped.values():
                    if not any(state(k) == wanted for k in keys):
                        continue
                    if wanted != "verified":
                        gaps = [
                            k
                            for k in keys
                            if state(k) in {"needs_consolidation", "unverified"}
                        ]
                        pool.append(min(gaps, key=lambda k: ORDER[k.difficulty]))
                    else:
                        dated = [
                            k
                            for k in keys
                            if state(k) == "verified" and verified_at(k) is not None
                        ]
                        if dated:
                            pool.append(
                                min(dated, key=lambda k: (verified_at(k), key_order(k)))
                            )
                if pool:
                    reason = wanted
                    break
            if reason == "verified" and pool:
                earliest = min(
                    when for k in pool if (when := verified_at(k)) is not None
                )
                pool = [k for k in pool if verified_at(k) == earliest]
    pool.sort(key=key_order)
    return Selection(
        target=random.Random(seed).choice(pool) if pool else None,
        candidates=pool,
        reason=reason if pool else "no_eligible_target",
        excluded=excluded,
    )
