"""Deterministic projections at immutable original-answer positions.

Inputs are server-validated observations, not model/self-reported pass flags.
Replacing an interpretation keeps its original position; no clock-based expiry,
reward mutation or unlock operation occurs here.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.capabilities.catalog import EvidenceKey

RULE_VERSION = "capability-evidence-v1"
Status = Literal["unverified", "verified", "needs_consolidation"]


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["ordinary", "boss"] = "ordinary"
    original_id: uuid.UUID
    run_id: uuid.UUID
    order: int
    submitted_at: datetime
    order_source: Literal["user_locked", "legacy_created_at_uuid"]
    target: EvidenceKey
    observation_id: uuid.UUID | None
    observation_sequence: int | None
    frozen_sequence: int | None
    outcome: str
    # Only the validated complete-history novelty adapter may supply this fact.
    qualified_novelty: bool
    case_digest: str | None
    judgment_ids: list[str]
    review_id: uuid.UUID | None = None
    review_decision: str | None = None
    semantic_reliability: Literal["unverified"] = "unverified"


class Transition(BaseModel):
    evidence: Evidence
    status: Status
    streak: int
    counted: bool


class CapabilityState(BaseModel):
    target: EvidenceKey
    status: Status = "unverified"
    streak: int = 0
    latest_verified_at: datetime | None = None
    recovery_started_at_order: int | None = None
    history: list[Transition] = []


class EvidenceMap(BaseModel):
    rule_version: str = RULE_VERSION
    semantic_reliability: Literal["unverified"] = "unverified"
    states: list[CapabilityState]


def project(records: list[Evidence]) -> EvidenceMap:
    # Caller selects the latest interpretation per original. Reject duplicates
    # instead of letting caller order turn the same exam into two successes.
    grouped: dict[uuid.UUID, list[Evidence]] = {}
    order_owners: dict[int, uuid.UUID] = {}
    for record in records:
        if (
            record.order in order_owners
            and order_owners[record.order] != record.original_id
        ):
            raise ValueError("ambiguous original order")
        order_owners[record.order] = record.original_id
        grouped.setdefault(record.original_id, []).append(record)
    for bundle in grouped.values():
        if len(bundle) == 1:
            continue
        if (
            any(r.kind != "boss" for r in bundle)
            or len({r.target for r in bundle}) != len(bundle)
            or len(
                {
                    (
                        r.run_id,
                        r.order,
                        r.submitted_at,
                        r.observation_id,
                        r.observation_sequence,
                        r.frozen_sequence,
                        r.case_digest,
                    )
                    for r in bundle
                }
            )
            != 1
            or len({j for r in bundle for j in r.judgment_ids})
            != sum(len(r.judgment_ids) for r in bundle)
        ):
            raise ValueError("duplicate original or invalid Boss judgment bundle")
    states: dict[EvidenceKey, CapabilityState] = {}
    seen: dict[EvidenceKey, set[str]] = {}
    for record in sorted(records, key=lambda r: r.order):
        state = states.setdefault(record.target, CapabilityState(target=record.target))
        digests = seen.setdefault(record.target, set())
        counted = False
        valid = record.qualified_novelty and bool(record.judgment_ids)
        if valid and record.outcome == "evidenced_fail":
            state.streak = 0
            if state.status == "verified" or (
                record.kind == "boss" and state.status == "unverified"
            ):
                state.status = "needs_consolidation"
                state.recovery_started_at_order = record.order
            counted = True
        elif (
            valid
            and record.outcome == "independent_pass_candidate"
            and record.case_digest
            and record.case_digest not in digests
        ):
            # Digest is only duplicate defense; semantic difference came from
            # the complete-history novelty assessment, not this comparison.
            state.streak += 1
            counted = True
            if state.streak >= 2:
                state.status = "verified"
                state.latest_verified_at = record.submitted_at
                state.recovery_started_at_order = None
        if record.case_digest:
            digests.add(record.case_digest)
        state.history.append(
            Transition(
                evidence=record,
                status=state.status,
                streak=state.streak,
                counted=counted,
            )
        )
    return EvidenceMap(states=list(states.values()))
