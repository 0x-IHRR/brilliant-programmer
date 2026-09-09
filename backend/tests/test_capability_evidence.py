import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.capabilities.catalog import EvidenceKey
from app.capabilities.evidence import Evidence, project

KEY = EvidenceKey(capability_id="test", difficulty="基础", background_id="one")


def evidence(position, outcome="independent_pass_candidate", **changes):
    return Evidence(
        original_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        order=position,
        submitted_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=position),
        order_source="user_locked",
        target=changes.pop("target", KEY),
        observation_id=uuid.uuid4(),
        observation_sequence=position + 100,
        frozen_sequence=4,
        outcome=outcome,
        qualified_novelty=changes.pop("qualified_novelty", True),
        case_digest=changes.pop("case_digest", str(position)),
        judgment_ids=["j1"],
        **changes,
    )


def test_first_verification_and_two_new_pass_recovery_preserve_history():
    result = project(
        [evidence(1), evidence(2), evidence(3, "evidenced_fail"), evidence(4)]
    )
    state = result.states[0]
    assert (state.status, state.streak, state.recovery_started_at_order) == (
        "needs_consolidation",
        1,
        3,
    )
    assert state.latest_verified_at == state.history[1].evidence.submitted_at
    result = project([t.evidence for t in state.history] + [evidence(5)])
    assert result.states[0].status == "verified"
    assert len(result.states[0].history) == 5


@pytest.mark.parametrize(
    "outcome",
    [
        "practice",
        "unclear",
        "disputed",
        "invalid_case",
        "system_failure",
        "pending_delivery",
        "no_qualified_case",
    ],
)
def test_inconclusive_or_ordinary_does_not_increment_or_break(outcome):
    state = project([evidence(1), evidence(2, outcome), evidence(3)]).states[0]
    assert (state.status, state.streak) == ("verified", 2)
    assert not state.history[1].counted


def test_failure_before_verification_and_during_recovery_clears_streak():
    state = project([evidence(1), evidence(2, "evidenced_fail"), evidence(3)]).states[0]
    assert (state.status, state.streak) == ("unverified", 1)
    state = project(
        [
            evidence(1),
            evidence(2),
            evidence(3, "evidenced_fail"),
            evidence(4),
            evidence(5, "evidenced_fail"),
            evidence(6),
        ]
    ).states[0]
    assert (state.status, state.streak) == ("needs_consolidation", 1)


def test_original_order_not_observation_arrival_and_replacement_recomputes():
    records = [evidence(1), evidence(2, "evidenced_fail"), evidence(3)]
    assert (
        project(list(reversed(records))).model_dump() == project(records).model_dump()
    )
    corrected = records[1].model_copy(
        update={"outcome": "disputed", "observation_sequence": 999}
    )
    assert project([records[2], corrected, records[0]]).states[0].status == "verified"
    assert records[1].outcome == "evidenced_fail"


def test_scope_duplicates_and_novelty_are_not_guessed_from_hash():
    other = KEY.model_copy(update={"background_id": "two"})
    hard = KEY.model_copy(update={"difficulty": "进阶"})
    result = project([evidence(1), evidence(2, target=other), evidence(3, target=hard)])
    assert all(s.status == "unverified" and s.streak == 1 for s in result.states)
    assert project([evidence(1), evidence(2, case_digest="1")]).states[0].streak == 1
    assert (
        project([evidence(1), evidence(2, qualified_novelty=False)]).states[0].streak
        == 1
    )
    same = evidence(1)
    with pytest.raises(ValueError, match="duplicate original"):
        project([same, same])


def test_elapsed_time_does_not_expire_verified():
    state = project([evidence(1), evidence(2), evidence(90000, "practice")]).states[0]
    assert state.status == "verified"
    assert state.latest_verified_at == state.history[1].evidence.submitted_at


def test_boss_bundle_keeps_one_original_and_distinct_judgments_only():
    first = evidence(1, kind="boss")
    second = first.model_copy(
        update={
            "target": KEY.model_copy(update={"background_id": "two"}),
            "judgment_ids": ["j2"],
            "outcome": "evidenced_fail",
        }
    )
    states = project([first, second]).states
    assert [s.status for s in states] == ["unverified", "needs_consolidation"]
    assert (
        states[0].history[0].evidence.original_id
        == states[1].history[0].evidence.original_id
    )
    for changed in [
        {"kind": "ordinary"},
        {"judgment_ids": ["j1"]},
        {"observation_id": uuid.uuid4()},
        {"run_id": uuid.uuid4()},
        {"order": 2},
    ]:
        with pytest.raises(ValueError, match="duplicate original"):
            project([first, second.model_copy(update=changed)])
    with pytest.raises(ValueError, match="duplicate original"):
        project(
            [
                first.model_copy(update={"kind": "ordinary"}),
                second.model_copy(update={"kind": "ordinary"}),
            ]
        )


@pytest.mark.parametrize(
    "outcome",
    ["practice", "pending_delivery", "invalid_case", "unclear", "system_failure"],
)
def test_boss_without_valid_failure_cannot_create_shortfall(outcome):
    state = project([evidence(1, outcome, kind="boss")]).states[0]
    assert state.status == "unverified" and not state.history[0].counted
    state = project(
        [evidence(1, "evidenced_fail", kind="boss", qualified_novelty=False)]
    ).states[0]
    assert state.status == "unverified" and not state.history[0].counted
