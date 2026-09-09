"""Source/route contracts only, not real-project or model-quality acceptance."""

import json
import uuid

import pytest

from app.capabilities.catalog import EvidenceKey
from app.project.analysis import syntax_map
from app.project.schema import (
    FileEntry,
    Fragment,
    Location,
    ProjectMap,
    Repository,
    Snapshot,
)
from app.project.training_rules import (
    ModuleGoal,
    confirm_route,
    generation_input,
    propose,
    start,
    validate_project_candidate,
)
from app.training.topic_rules import Goal


@pytest.fixture
def material():
    text = "def apply(request):\n    return request.confirmed\n"
    fragment = Fragment(
        path="src/app.py", blob="b" * 40, start=1, end=2, total_lines=2, text=text
    )
    snapshot = Snapshot(
        repository=Repository(
            owner="public-owner",
            name="project",
            commit="a" * 40,
            tree="c" * 40,
            ref="feature/one",
        ),
        entries=[
            FileEntry(
                path=fragment.path,
                sha=fragment.blob,
                kind="blob",
                mode="100644",
                size=len(text),
            )
        ],
        fragments=[fragment],
        listing_complete=True,
    )
    goal = ModuleGoal(
        module_path=fragment.path,
        goal=Goal(
            target=EvidenceKey(
                capability_id="network.delivery",
                difficulty="基础",
                background_id="network-evidence-v1",
            ),
            text="判断确认与执行结果的区别",
            focus="从请求处理代码寻找必要的证据",
        ),
        evidence=(
            Location(path=fragment.path, start=1, end=2, quote=text.rstrip("\n")),
        ),
    )
    return snapshot, syntax_map([fragment]), goal


def selection(material):
    snapshot, mapping, goal = material
    route = propose(uuid.uuid4(), snapshot, mapping, (goal,), key="")
    confirmed = confirm_route(route, route.route.id)
    return start(confirmed, route.route.id, route.route.nodes[0].id, verified=set())


def test_fixed_source_requires_confirmation_and_omits_other_repository_data(material):
    snapshot, mapping, goal = material
    route = propose(uuid.uuid4(), snapshot, mapping, (goal,), key="")
    with pytest.raises(ValueError):
        start(route, route.route.id, route.route.nodes[0].id, verified=set())
    saved = selection(material)
    ref = saved.references[0]
    assert ref.blob == "b" * 40
    assert ref.source.version == snapshot.repository.commit
    assert ref.source.url.endswith(f"/blob/{'a' * 40}/src/app.py#L1-L2")
    assert ref.source.text == goal.evidence[0].quote
    before = saved.model_dump_json()
    snapshot.fragments.clear()
    assert saved.model_dump_json() == before
    payload = generation_input(saved, "")
    assert set(payload) == {"goal", "module", "sources", "simulation_label"}
    assert payload["simulation_label"] == "教学模拟"
    assert "feature/one" not in json.dumps(payload)
    assert payload["goal"]["focus"] == saved.goal.focus


@pytest.mark.parametrize(
    "tamper",
    [
        "quote",
        "range",
        "blob",
        "symlink",
        "excluded",
        "missing_entry",
        "fragment_lines",
    ],
)
def test_forged_or_unread_source_rejected(material, tamper):
    snapshot, mapping, goal = material
    if tamper == "quote":
        goal = goal.model_copy(
            update={
                "evidence": (
                    goal.evidence[0].model_copy(
                        update={"quote": "invented execution result"}
                    ),
                )
            }
        )
    elif tamper == "range":
        goal = goal.model_copy(
            update={"evidence": (goal.evidence[0].model_copy(update={"end": 3}),)}
        )
    elif tamper == "blob":
        snapshot.entries[0] = snapshot.entries[0].model_copy(update={"sha": "d" * 40})
    elif tamper == "symlink":
        snapshot.entries[0] = snapshot.entries[0].model_copy(update={"mode": "120000"})
    elif tamper == "excluded":
        snapshot.excluded[goal.module_path] = "unread secret"
    elif tamper == "missing_entry":
        snapshot.entries.clear()
    else:
        snapshot.fragments[0] = snapshot.fragments[0].model_copy(update={"end": 3})
    with pytest.raises(ValueError):
        propose(uuid.uuid4(), snapshot, mapping, (goal,), key="")


def test_later_slice_is_usable_without_claiming_python_runtime_semantics(material):
    snapshot, _, goal = material
    fragment = snapshot.fragments[0].model_copy(
        update={"start": 100, "end": 101, "total_lines": 200}
    )
    snapshot.fragments[0] = fragment
    mapping = syntax_map([fragment])
    assert not any(f.kind == "call" for f in mapping.confirmed)
    goal = goal.model_copy(
        update={
            "evidence": (
                goal.evidence[0].model_copy(update={"start": 100, "end": 101}),
            )
        }
    )
    picked = selection((snapshot, mapping, goal))
    assert picked.references[0].source.url.endswith("#L100-L101")


def test_partial_failure_keeps_valid_nodes_and_reports_missing(material):
    snapshot, mapping, goal = material
    mapping.missing.append("other module unavailable")
    snapshot.excluded["unread.bin"] = "binary excluded"
    missing = goal.model_copy(
        update={
            "goal": goal.goal.model_copy(update={"focus": "检查尚缺日志"}),
            "evidence": (),
            "missing": ("缺少执行结果记录",),
        }
    )
    route = propose(uuid.uuid4(), snapshot, mapping, (goal, missing), key="")
    route = confirm_route(route, route.route.id)
    assert "other module unavailable" in route.map_missing
    assert any("unread.bin" in x for x in route.map_missing)
    assert start(route, route.route.id, route.route.nodes[0].id, verified=set())
    with pytest.raises(ValueError, match="缺少执行结果记录"):
        start(route, route.route.id, route.route.nodes[1].id, verified=set())
    assert len(route.bindings) == 2 and len(snapshot.fragments) == 1
    with pytest.raises(ValueError, match="module"):
        propose(
            uuid.uuid4(),
            snapshot,
            ProjectMap(unverified=mapping.confirmed),
            (goal,),
            key="",
        )
    empty = propose(uuid.uuid4(), snapshot, mapping, (), key="")
    with pytest.raises(ValueError):
        confirm_route(empty, empty.route.id)


def test_reorder_preserves_nodes_edit_requires_new_confirmation_and_old_snapshot_survives(
    material,
):
    snapshot, mapping, goal = material
    other = goal.model_copy(
        update={"goal": goal.goal.model_copy(update={"focus": "检查未确认结果"})}
    )
    identity = uuid.uuid4()
    old = propose(identity, snapshot, mapping, (goal, other), key="")
    old_json = old.model_dump_json()
    newer = propose(
        identity,
        snapshot,
        mapping,
        (other, goal),
        key="",
        previous=old,
        expected_version=old.route.id,
    )
    assert [n.id for n in newer.route.nodes] == [
        n.id for n in reversed(old.route.nodes)
    ]
    changed = goal.model_copy(
        update={"goal": goal.goal.model_copy(update={"focus": "新的训练重点"})}
    )
    edited = propose(
        identity,
        snapshot,
        mapping,
        (changed,),
        key="",
        previous=old,
        expected_version=old.route.id,
    )
    assert edited.route.nodes[0].id not in {n.id for n in old.route.nodes}
    assert not edited.route.confirmed and old.model_dump_json() == old_json
    with pytest.raises(ValueError):
        confirm_route(edited, old.route.id)
    with pytest.raises(ValueError):
        propose(
            identity,
            snapshot,
            mapping,
            (goal,),
            key="",
            previous=newer,
            expected_version=old.route.id,
        )


def test_module_order_is_not_a_prerequisite_and_opened_catalog_must_match(material):
    snapshot, mapping, goal = material
    advanced = goal.model_copy(
        update={
            "goal": goal.goal.model_copy(
                update={
                    "target": goal.goal.target.model_copy(update={"difficulty": "进阶"})
                }
            )
        }
    )
    route = propose(uuid.uuid4(), snapshot, mapping, (advanced, goal), key="")
    route = confirm_route(route, route.route.id)
    # The later basic node can start even though the earlier advanced one cannot.
    assert start(route, route.route.id, route.route.nodes[1].id, verified=set())
    with pytest.raises(ValueError):
        start(route, route.route.id, route.route.nodes[0].id, verified=set())
    with pytest.raises(ValueError):
        start(
            route,
            route.route.id,
            route.route.nodes[0].id,
            verified=set(),
            opened={advanced.goal.target},
            opened_catalog_version="old",
        )
    assert start(
        route,
        route.route.id,
        route.route.nodes[0].id,
        verified=set(),
        opened={advanced.goal.target},
        opened_catalog_version=route.route.catalog_version,
    )


def case_for(saved):
    source = saved.references[0].source
    return {
        "case": {
            "target": saved.goal.target.model_dump(),
            "catalog_version": saved.goal.catalog_version,
            "title": "教学模拟：确认状态",
            "task": "根据代码与教学假设判断确认是否代表执行。",
            "assumptions": [
                "教学假设：当前请求已处理但确认丢失，不是项目真实运行记录。"
            ],
            "evidence": [
                {
                    "id": "code",
                    "label": "教学材料",
                    "text": source.text,
                    "facts": {"return_expression": "request.confirmed"},
                    "citations": [{"source_id": source.id, "quote": source.text}],
                }
            ],
            "judgments": [
                {
                    "id": "judge",
                    "kind": "choice",
                    "prompt": "确认缺失能证明没有执行吗？",
                    "options": ["不能", "能"],
                    "evidence_ids": ["code"],
                }
            ],
            "rubric": [
                {
                    "judgment_id": "judge",
                    "acceptable_options": [0],
                    "reasoning": "源码只返回确认状态；教学假设给出了处理成功而确认丢失。",
                    "evidence_ids": ["code"],
                    "counterexample": "若有持久执行结果，可进一步判断。",
                    "help_boundary": "说明判断结论将影响独立性",
                }
            ],
            "variation": {
                "causal_condition": "教学假设确认丢失",
                "expected_evidence": "需要持久结果",
                "decision_effect": "不能直接判断未执行",
            },
            "missing_evidence": [],
            "conflicts": [],
        },
        "materials": [{"evidence_id": "code", "kind": "code_excerpt"}],
    }


def test_case_keeps_variation_and_explicit_material_origin_without_qualifying_novelty(
    material,
):
    saved = selection(material)
    raw = case_for(saved)
    checked = validate_project_candidate(json.dumps(raw), saved, "")
    assert (
        checked.case.variation.causal_condition
        == raw["case"]["variation"]["causal_condition"]
    )
    assert set(checked.model_dump()) == {"case", "materials"}
    for kind in ["synthetic_log", "teaching_assumption"]:
        raw["materials"][0]["kind"] = kind
        assert (
            validate_project_candidate(json.dumps(raw), saved, "").materials[0].kind
            == kind
        )
    raw["materials"] = []
    with pytest.raises(ValueError):
        validate_project_candidate(json.dumps(raw), saved, "")


@pytest.mark.parametrize("tamper", ["source", "excerpt", "missing", "secret"])
def test_case_wrong_sources_runtime_claim_and_missing_evidence_rejected(
    material, tamper
):
    saved = selection(material)
    raw = case_for(saved)
    key = ""
    if tamper == "source":
        raw["case"]["evidence"][0]["citations"][0]["source_id"] = "another-commit"
    elif tamper == "excerpt":
        raw["case"]["evidence"][0]["text"] = "真实系统已运行成功"
    elif tamper == "missing":
        raw["case"]["missing_evidence"] = ["缺少执行记录"]
    else:
        key = "fake-test-key-only-123456789"
        raw["case"]["title"] = key
    with pytest.raises(ValueError):
        validate_project_candidate(json.dumps(raw), saved, key)


def test_source_secret_and_cross_module_substitution_are_not_allowed(material):
    snapshot, mapping, goal = material
    with pytest.raises(ValueError):
        propose(uuid.uuid4(), snapshot, mapping, (goal,), key="request.confirmed")
    leaked = goal.model_copy(
        update={
            "goal": goal.goal.model_copy(
                update={"focus": "fake-only-private-key-987654321"}
            )
        }
    )
    with pytest.raises(ValueError):
        propose(
            uuid.uuid4(),
            snapshot,
            mapping,
            (leaked,),
            key="fake-only-private-key-987654321",
        )
    without = goal.model_copy(update={"evidence": ()})
    with pytest.raises(ValueError):
        propose(uuid.uuid4(), snapshot, mapping, (without,), key="")
    # A goal for a confirmed module cannot silently substitute only another file.
    second = snapshot.fragments[0].model_copy(
        update={"path": "src/other.py", "blob": "e" * 40}
    )
    snapshot.fragments.append(second)
    snapshot.entries.append(
        FileEntry(path=second.path, sha=second.blob, kind="blob", mode="100644")
    )
    altered = goal.model_copy(
        update={
            "evidence": (goal.evidence[0].model_copy(update={"path": second.path}),)
        }
    )
    with pytest.raises(ValueError, match="selected module"):
        propose(uuid.uuid4(), snapshot, mapping, (altered,), key="")
