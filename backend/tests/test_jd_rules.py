"""Controlled JD contracts, not extraction accuracy or end-to-end verification."""

import uuid

import pytest

from app.capabilities.catalog import EvidenceKey
from app.capabilities.evidence import CapabilityState, EvidenceMap
from app.training.jd_rules import (
    Analysis,
    Document,
    Quote,
    Requirement,
    Role,
    analysis_input,
    confirm_route,
    evidence_for,
    generation_input,
    propose,
    start,
)
from app.training.topic_rules import Goal


def sample(count=1):
    document = Document(
        id=uuid.uuid4(),
        text="后端工程师：处理请求重试。另有前端岗位。联系邮箱仅留在原文。",
    )
    quote = Quote(start=6, end=12, text="处理请求重试")
    goal = Goal(
        target=EvidenceKey(
            capability_id="network.delivery",
            difficulty="基础",
            background_id="network-evidence-v1",
        ),
        text="从执行证据判断重试",
        focus="区分执行与确认",
    )
    requirements = tuple(
        Requirement(
            quote=quote,
            basis="inferred",
            explanation="从重试要求推演教学判断，技术背景是教学设定",
            goal=goal.model_copy(update={"text": f"判断重试的情境{i}"}),
        )
        for i in range(count)
    )
    role = Role(
        name="后端工程师",
        quote=Quote(start=0, end=5, text="后端工程师"),
        requirements=requirements,
    )
    return document, Analysis(
        kind="roles", message="先确认教学重点；不是公司的真实题目", roles=(role,)
    )


@pytest.mark.parametrize("count", [1, 2, 6, 9])
def test_jd_route_does_not_inherit_free_topic_three_to_five_limit(count):
    doc, analysis = sample(count)
    route = propose(doc, analysis)
    assert len(route.route.nodes) == count
    assert not route.route.confirmed
    with pytest.raises(ValueError):
        start(route, route.route.id, route.route.nodes[0].id, verified=set())
    confirmed = confirm_route(route, route.route.id)
    snapshot = start(confirmed, route.route.id, route.route.nodes[0].id, verified=set())
    assert snapshot.simulation_label == "教学模拟"
    assert snapshot.document_version == doc.id
    assert snapshot.requirement.basis == "inferred"


@pytest.mark.parametrize("kind", ["no_requirements", "clarify"])
def test_unresolved_input_requests_supplement_without_route(kind):
    document = Document(id=uuid.uuid4(), text="欢迎加入我们")
    candidate = Analysis(kind=kind, message="请补充具体岗位要求")
    with pytest.raises(ValueError):
        propose(document, candidate)


def test_mixed_jobs_require_explicit_choice_and_never_inherit_other_role_nodes():
    doc, candidate = sample()
    role = candidate.roles[0]
    second = role.model_copy(
        update={"name": "前端岗位", "quote": Quote(start=15, end=19, text="前端岗位")}
    )
    mixed = candidate.model_copy(update={"roles": (role, second)})
    with pytest.raises(ValueError):
        propose(doc, mixed)
    first = propose(doc, mixed, selected_role=0)
    selected = propose(
        doc, mixed, selected_role=1, previous=first, expected_version=first.route.id
    )
    assert selected.role_name == "前端岗位"
    assert selected.route.nodes[0].id != first.route.nodes[0].id
    with pytest.raises(ValueError):
        propose(doc, mixed, selected_role=2)


def test_exact_original_span_cannot_be_replaced_by_model_claim():
    doc, candidate = sample()
    requirement = candidate.roles[0].requirements[0]
    for quote in [
        Quote(start=6, end=12, text="虚构要求内容"),
        Quote(start=0, end=1000, text=doc.text),
    ]:
        role = candidate.roles[0].model_copy(
            update={"requirements": (requirement.model_copy(update={"quote": quote}),)}
        )
        with pytest.raises(ValueError):
            propose(doc, candidate.model_copy(update={"roles": (role,)}))
    with pytest.raises(ValueError):
        Requirement.model_validate({**requirement.model_dump(), "confidence": 1})


def test_reorder_keeps_completion_identity_edit_and_new_document_do_not():
    doc, candidate = sample(6)
    original = propose(doc, candidate)
    role = candidate.roles[0]
    reversed_candidate = candidate.model_copy(
        update={
            "roles": (
                role.model_copy(
                    update={"requirements": tuple(reversed(role.requirements))}
                ),
            )
        }
    )
    reordered = propose(
        doc, reversed_candidate, previous=original, expected_version=original.route.id
    )
    assert [n.id for n in reordered.route.nodes] == [
        n.id for n in reversed(original.route.nodes)
    ]
    edited = role.requirements[0].model_copy(
        update={
            "goal": role.requirements[0].goal.model_copy(
                update={"focus": "改为先核执行记录"}
            )
        }
    )
    changed = candidate.model_copy(
        update={
            "roles": (
                role.model_copy(
                    update={"requirements": (edited, *role.requirements[1:])}
                ),
            )
        }
    )
    version = propose(
        doc, changed, previous=original, expected_version=original.route.id
    )
    assert len(version.route.nodes) == 6
    assert version.route.nodes[0].id != original.route.nodes[0].id
    assert version.route.nodes[1:] == original.route.nodes[1:]
    assert not version.route.confirmed
    new_doc = doc.model_copy(update={"id": uuid.uuid4()})
    newer = propose(
        new_doc, candidate, previous=original, expected_version=original.route.id
    )
    assert {n.id for n in newer.route.nodes}.isdisjoint(
        n.id for n in original.route.nodes
    )
    with pytest.raises(ValueError):
        confirm_route(version, original.route.id)
    with pytest.raises(ValueError):
        propose(doc, candidate, previous=version, expected_version=original.route.id)


def test_unknown_background_and_unavailable_evidence_are_not_lack_of_skill():
    doc, candidate = sample()
    requirement = candidate.roles[0].requirements[0]
    unknown = requirement.model_copy(update={"goal": None})
    role = candidate.roles[0].model_copy(update={"requirements": (unknown,)})
    route = propose(doc, candidate.model_copy(update={"roles": (role,)}))
    assert not route.route.nodes
    with pytest.raises(ValueError):
        confirm_route(route, route.route.id)
    assert evidence_for(unknown, EvidenceMap(states=[])).status == "unknown"
    assert evidence_for(requirement, None).streak is None
    assert evidence_for(requirement, EvidenceMap(states=[])).status == "unverified"
    assert requirement.goal
    other = requirement.goal.target.model_copy(
        update={"background_id": "another-background"}
    )
    states = EvidenceMap(
        states=[CapabilityState(target=other, status="verified", streak=2)]
    )
    assert evidence_for(requirement, states).status == "unverified"
    for status in ["verified", "needs_consolidation"]:
        states = EvidenceMap(
            states=[
                CapabilityState(target=requirement.goal.target, status=status, streak=2)
            ]
        )
        assert evidence_for(requirement, states).status == status


def test_catalog_and_real_prerequisite_gate_still_apply():
    doc, candidate = sample()
    req = candidate.roles[0].requirements[0]
    assert req.goal
    advanced = req.model_copy(
        update={
            "goal": req.goal.model_copy(
                update={
                    "target": req.goal.target.model_copy(update={"difficulty": "进阶"})
                }
            )
        }
    )
    role = candidate.roles[0].model_copy(update={"requirements": (advanced,)})
    route = propose(doc, candidate.model_copy(update={"roles": (role,)}))
    route = confirm_route(route, route.route.id)
    with pytest.raises(ValueError):
        start(route, route.route.id, route.route.nodes[0].id, verified=set())
    opened = {route.route.nodes[0].target}
    with pytest.raises(ValueError):
        start(
            route,
            route.route.id,
            route.route.nodes[0].id,
            verified=set(),
            opened=opened,
            opened_catalog_version="old",
        )
    assert start(
        route,
        route.route.id,
        route.route.nodes[0].id,
        verified=set(),
        opened=opened,
        opened_catalog_version=route.route.catalog_version,
    )
    invalid = req.model_copy(
        update={
            "goal": req.goal.model_copy(
                update={
                    "target": req.goal.target.model_copy(
                        update={"background_id": "company-real-stack"}
                    )
                }
            )
        }
    )
    with pytest.raises(ValueError):
        propose(
            doc,
            candidate.model_copy(
                update={
                    "roles": (role.model_copy(update={"requirements": (invalid,)}),)
                }
            ),
        )


def test_outbound_generation_omits_full_jd_and_uses_confirmed_focus():
    doc, candidate = sample()
    route = propose(doc, candidate)
    route = confirm_route(route, route.route.id)
    snapshot = start(route, route.route.id, route.route.nodes[0].id, verified=set())
    assert analysis_input(doc) == {"jd_text": doc.text}
    payload = generation_input(snapshot)
    assert set(payload) == {
        "target",
        "goal",
        "focus",
        "requirement_quote",
        "basis",
        "simulation_label",
    }
    assert payload["focus"] == snapshot.focus
    assert payload["requirement_quote"] == "处理请求重试"
    assert "联系邮箱" not in str(payload)
    assert payload["simulation_label"] == "教学模拟"
