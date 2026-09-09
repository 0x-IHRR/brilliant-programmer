import pytest
from fastapi import HTTPException

from app.capabilities.catalog import CATALOG, EvidenceKey
from app.capabilities.evidence import CapabilityState, EvidenceMap
from app.capabilities.unlocks import access, level_for


def test_all_required_and_each_alternative_group_and_retained_opening():
    target = next(
        EvidenceKey(
            capability_id=c.id,
            difficulty=tier.difficulty,
            background_id=c.background_id,
        )
        for d in CATALOG.domains
        for c in d.capabilities
        for tier in c.levels
        if len(tier.alternatives) > 1
    )
    level = level_for(target)
    verified = set(level.required) | {group[0] for group in level.alternatives}
    evidence = EvidenceMap(
        states=[CapabilityState(target=k, status="verified") for k in verified]
    )
    assert access(target, evidence, False).eligible
    evidence.states = [
        s for s in evidence.states if s.target != level.alternatives[-1][0]
    ]
    result = access(target, evidence, False)
    assert not result.eligible and result.missing_alternatives == [
        list(level.alternatives[-1])
    ]
    assert access(target, evidence, True).eligible
    assert access(target, evidence, True).opened


def test_wrong_background_difficulty_self_report_and_recovery_do_not_bypass():
    target = next(
        EvidenceKey(
            capability_id=c.id,
            difficulty=tier.difficulty,
            background_id=c.background_id,
        )
        for d in CATALOG.domains
        for c in d.capabilities
        for tier in c.levels
        if tier.required
    )
    level = level_for(target)
    evidence = EvidenceMap(
        states=[
            CapabilityState(target=k, status="needs_consolidation")
            for k in level.required
        ]
    )
    assert not access(target, evidence, False).eligible
    evidence.states[0].status = "verified"
    expected = level.satisfied_by({evidence.states[0].target})
    assert access(target, evidence, False).eligible == expected
    wrong = EvidenceMap(
        states=[
            CapabilityState(
                target=k.model_copy(update={"background_id": "other"}),
                status="verified",
            )
            for k in level.required
        ]
    )
    assert not access(target, wrong, False).eligible
    with pytest.raises(HTTPException):
        level_for(target.model_copy(update={"background_id": "other"}))
