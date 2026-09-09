from datetime import UTC, datetime, timedelta

from app.capabilities.catalog import EvidenceKey
from app.capabilities.evidence import CapabilityState, EvidenceMap
from app.capabilities.unlocks import UnitAccess
from app.training.recommendations import choose

NOW = datetime(2026, 9, 9, tzinfo=UTC)


def key(name, difficulty="基础"):
    return EvidenceKey(capability_id=name, difficulty=difficulty, background_id="test")


def unit(target, eligible=True):
    return UnitAccess(
        target=target,
        opened=False,
        eligible=eligible,
        missing_required=[] if eligible else [key("missing")],
        missing_alternatives=[],
    )


def select(units, states=(), **kwargs):
    return choose(
        units=units,
        evidence=EvidenceMap(states=list(states)),
        preference=kwargs.pop("preference", "recommended"),
        has_record=kwargs.pop("has_record", True),
        delivered=kwargs.pop("delivered", 0),
        now=NOW,
        seed=kwargs.pop("seed", "fixed-seed"),
        **kwargs,
    )


def test_priority_is_per_capability_and_lowest_gap_not_duplicate_tiers():
    a, advanced, b = key("a"), key("a", "进阶"), key("b")
    result = select(
        [unit(b), unit(advanced), unit(a)],
        [CapabilityState(target=advanced, status="needs_consolidation")],
    )
    assert result.candidates == [a] and result.reason == "needs_consolidation"
    result = select([unit(a), unit(advanced), unit(b)])
    assert result.candidates == [a, b]
    assert select([unit(b), unit(a), unit(advanced)]).target == result.target


def test_fifth_success_prefers_seven_day_review_and_empty_review_falls_back():
    a, b = key("a"), key("b")
    old = CapabilityState(
        target=a, status="verified", latest_verified_at=NOW - timedelta(days=7)
    )
    assert select([unit(a), unit(b)], [old], delivered=3).target == b
    result = select([unit(a), unit(b)], [old], delivered=4)
    assert result.target == a and result.reason == "seventh_day_review"
    recent = old.model_copy(update={"latest_verified_at": NOW - timedelta(days=6)})
    assert select([unit(a), unit(b)], [recent], delivered=4).target == b
    assert select([unit(a), unit(b)], [old], delivered=9).target == a


def test_fixed_difficulty_and_first_entry_do_not_change_tiers():
    basic, advanced = key("a"), key("b", "进阶")
    assert select([unit(basic), unit(advanced)], preference="进阶").target == advanced
    assert (
        select(
            [unit(basic), unit(advanced)], preference="进阶", has_record=False
        ).target
        == basic
    )
    assert (
        select([unit(basic), unit(advanced, False)], preference="进阶").target is None
    )


def test_oldest_verified_uses_actual_verified_tier_and_uniform_equal_pool():
    a, b, c = key("a", "进阶"), key("b"), key("c")
    states = [
        CapabilityState(
            target=k, status="verified", latest_verified_at=NOW - timedelta(days=d)
        )
        for k, d in [(a, 9), (b, 9), (c, 3)]
    ]
    result = select([unit(c), unit(b), unit(a)], states)
    assert result.candidates == [a, b]
    choices = {
        select([unit(c), unit(b), unit(a)], states, seed=str(i)).target
        for i in range(100)
    }
    assert choices == {a, b}
    assert all(s.status == "verified" for s in states)


def test_new_direction_and_prerequisite_failure_keep_real_reasons():
    a, b = key("a"), key("b")
    result = select([unit(a), unit(b, False)], previous_capability="a")
    assert result.target is None
    assert {item["reason"] for item in result.excluded} == {
        "missing_prerequisites",
        "requested_other_direction",
    }


def test_actual_generation_payload_obeys_frozen_difficulty(monkeypatch):
    import asyncio
    import json

    from app.capabilities.catalog import CATALOG
    from app.training import generation

    captured = []

    async def transport(_service_url, _secret, payload):
        captured.append(json.loads(payload))
        return (
            json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode(),
            "application/json",
            {"total_tokens": 3},
        )

    monkeypatch.setattr(generation, "request_raw", transport)
    for tier in ["基础", "进阶", "综合"]:
        target = EvidenceKey(
            capability_id="network.delivery",
            difficulty=tier,
            background_id="network-evidence-v1",
        )
        asyncio.run(
            generation.generate(
                "https://provider.example.com",
                "fake",
                "synthetic-key",
                target,
                [],
                False,
            )
        )
        system = captured[-1]["messages"][0]["content"]
        context = json.loads(captured[-1]["messages"][1]["content"])
        assert "生成实际基础无前置" not in system
        assert "不自动降档" in system and "基础采用无前置的起步材料" in system
        assert context["target"]["difficulty"] == tier
        assert context["difficulty_criterion"] == CATALOG.difficulty_criteria[tier]
