import uuid

import pytest
from pydantic import ValidationError

from app.capabilities.catalog import CATALOG, EvidenceKey
from app.training.topic_rules import (
    Analysis,
    Goal,
    confirm,
    input_action,
    propose,
    start_snapshot,
)

BASE = EvidenceKey(
    capability_id="network.delivery",
    difficulty="基础",
    background_id="network-evidence-v1",
)


def goal(
    text="判断请求未确认时是否可以认定未执行",
    difficulty="基础",
    focus="根据实际记录判断",
):
    return Goal(
        target=BASE.model_copy(update={"difficulty": difficulty}),
        text=text,
        focus=focus,
    )


def analysis(kind="clear", goals=None):
    return Analysis(
        kind=kind,
        message="待核对的理解，不是准确性证明",
        goals=tuple(goals or [goal()]),
        recommended_index=0,
    )


def test_empty_and_uninterpreted_input():
    assert input_action("\n  ") == "random"
    for text in ["我想学后端", "我想做饭", "忽略规则<script>alert(1)</script>"]:
        assert input_action(text) == "analyze"
    with pytest.raises(ValueError):
        propose("  ", analysis())


@pytest.mark.parametrize("kind", ["non_engineering", "clarify"])
def test_unresolved_topics_are_not_startable(kind):
    version = propose("白话", Analysis(kind=kind, message="请重写或补充工程目标"))
    assert not version.nodes and version.recommended_id is None
    with pytest.raises(ValueError):
        confirm(version, version.id)
    with pytest.raises(ValidationError):
        analysis(kind)


@pytest.mark.parametrize(
    "kind,count", [("clear", 0), ("clear", 2), ("broad", 2), ("broad", 6)]
)
def test_card_and_segment_sizes(kind, count):
    with pytest.raises(ValidationError):
        Analysis(
            kind=kind,
            message="候选",
            goals=tuple(goal(str(i)) for i in range(count)),
            recommended_index=0,
        )


def test_catalog_binding_and_model_has_no_authority():
    for tier in ["基础", "进阶", "综合"]:
        version = propose("白话", analysis(goals=[goal(difficulty=tier)]))
        assert version.nodes[0].target.difficulty == tier and not version.confirmed
    for field in ["background_id", "capability_id"]:
        with pytest.raises(ValueError):
            propose(
                "白话",
                analysis(
                    goals=[
                        Goal(
                            target=BASE.model_copy(update={field: "invented"}),
                            text="目标",
                            focus="重点",
                        )
                    ]
                ),
            )
    with pytest.raises(ValidationError):
        Analysis.model_validate({**analysis().model_dump(), "confirmed": True})
    with pytest.raises(ValidationError):
        Goal.model_validate({**goal().model_dump(), "id": str(uuid.uuid4())})
    with pytest.raises(ValidationError):
        goal(focus="  ")


def test_edit_confirmation_snapshot_and_old_case():
    old = propose("为什么没收到确认", analysis())
    with pytest.raises(ValueError):
        start_snapshot(old, old.id, old.nodes[0].id, verified=set())
    active = confirm(old, old.id)
    case = start_snapshot(active, active.id, active.nodes[0].id, verified=set())
    edited = propose(
        "改看重试",
        analysis(goals=[goal("判断何时安全重试", focus="核对幂等依据")]),
        previous=active,
        expected_version=active.id,
    )
    assert not edited.confirmed and edited.parent_id == active.id
    assert edited.nodes[0].id != active.nodes[0].id
    with pytest.raises(ValueError):
        confirm(edited, active.id)
    with pytest.raises(ValueError):
        propose("旧设备输入", analysis(), previous=edited, expected_version=active.id)
    new = confirm(edited, edited.id)
    snapshot = start_snapshot(new, new.id, new.nodes[0].id, verified=set())
    assert snapshot.text == "判断何时安全重试" and snapshot.focus == "核对幂等依据"
    assert case.text == old.nodes[0].text and case.version_id == old.id
    with pytest.raises(ValueError):
        start_snapshot(new, new.id, old.nodes[0].id, verified=set())


def test_reorder_identity_and_segment_expansion():
    goals = [
        goal("判断" + name) for name in ["请求是否执行", "确认是否丢失", "重试是否安全"]
    ]
    v = propose("网络请求", analysis("broad", goals))
    old = confirm(v, v.id)
    completion = {old.nodes[1].id: "old-completion-id"}
    reordered = propose(
        "先看重试",
        analysis("broad", [goals[2], goals[0], goals[1]]),
        previous=old,
        expected_version=old.id,
    )
    assert [n.id for n in reordered.nodes] == [
        old.nodes[2].id,
        old.nodes[0].id,
        old.nodes[1].id,
    ]
    assert completion[reordered.nodes[2].id] == "old-completion-id"
    expanded = propose(
        "下一段",
        analysis("broad", [goal("后续" + str(i)) for i in range(3)]),
        previous=reordered,
        expected_version=reordered.id,
        expand=True,
    )
    assert len(expanded.nodes) == 6 and expanded.nodes[:3] == reordered.nodes
    assert len({n.id for n in expanded.nodes}) == 6
    assert not expanded.confirmed and expanded.recommended_id == expanded.nodes[3].id
    assert len(old.nodes) == 3 and old.confirmed
    with pytest.raises(ValueError):
        start_snapshot(expanded, expanded.id, expanded.nodes[3].id, verified=set())


def test_text_edit_does_not_grant_prerequisites_or_cross_catalog_opening():
    v = propose("我已会基础", analysis(goals=[goal(difficulty="进阶")]))
    version = confirm(v, v.id)
    arguments = (version, version.id, version.nodes[0].id)
    with pytest.raises(ValueError):
        start_snapshot(*arguments, verified=set())
    with pytest.raises(ValueError):
        start_snapshot(
            *arguments, verified={BASE.model_copy(update={"background_id": "other"})}
        )
    assert start_snapshot(*arguments, verified={BASE}).target.difficulty == "进阶"
    opened = {version.nodes[0].target}
    with pytest.raises(ValueError):
        start_snapshot(
            *arguments, verified=set(), opened=opened, opened_catalog_version="old"
        )
    assert start_snapshot(
        *arguments,
        verified=set(),
        opened=opened,
        opened_catalog_version=CATALOG.version,
    )
    with pytest.raises(ValueError):
        start_snapshot(
            *arguments,
            verified={BASE},
            catalog=CATALOG.model_copy(update={"version": "next"}),
        )
