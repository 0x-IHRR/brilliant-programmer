"""Replay a real anonymous GitHub acquisition through controlled teaching transport.

The source was read with production GitHub.resolve/acquire, never imported or run.
The 27-line retained excerpt is from pallets/itsdangerous (BSD-3-Clause),
commit 672971d66a2ef9f85151e53283113f33d642dabd, timed.py:132–158.
This is a software-flow witness, not a model-quality or human certification.
"""

import json
import uuid
from pathlib import Path

from app.capabilities.catalog import CATALOG, EvidenceKey
from app.project.analysis import syntax_map
from app.project.schema import Location, Snapshot
from app.project.training_rules import ModuleGoal
from app.training.topic_rules import Goal
from tests.test_accounts import client
from tests.test_evaluations import grading
from tests.test_evaluations import start as start_evaluation
from tests.test_evaluations import wait as wait_evaluation
from tests.test_model_config import account, save
from tests.test_project_training_api import begin
from tests.test_submissions import wait_submission
from tests.test_topics import wait_topic
from tests.test_training import provider as provider
from tests.test_training import start_worker, stop_worker, wait_run


def public_material():
    snapshot = Snapshot.model_validate_json(
        (Path(__file__).parent / "fixtures/project_timed_source.json").read_text()
    )
    fragment = snapshot.fragments[0]
    goal = ModuleGoal(
        module_path=fragment.path,
        goal=Goal(
            target=EvidenceKey(
                capability_id="testing.coverage",
                difficulty="基础",
                background_id="testing-evidence-v1",
            ),
            text="为时间戳签名校验补齐有效期边界测试",
            focus="比较 age 等于与超过 max_age 的观察结果，保留签名和时间戳有效的前提",
        ),
        evidence=(
            Location(
                path=fragment.path,
                start=fragment.start,
                end=fragment.end,
                quote=fragment.text.rstrip("\n"),
            ),
        ),
    )
    mapped = syntax_map(snapshot.fragments)
    mapped.missing.append(
        "仅留实际读取的 timed.py:132–158 用于本轮；未执行目标代码，其它范围不作完整性声明"
    )
    return snapshot, mapped, goal


def respond(payload):
    snapshot, _, goal = public_material()
    data = json.loads(payload["messages"][1]["content"])
    if "context" in data:
        return (
            {
                "accepted": True,
                "explanation": "受控核对实际源码中 age > max_age 与 age < 0 分支；模块映射到边界测试",
            }
            if "candidate" in data["context"]
            else {
                "goals": [goal.model_dump(mode="json")],
                "message": "先练时间有效期边界，模块顺序不构成必修链",
            }
        )
    if "candidate" in data:
        assert data["confirmed_topic"]["module_path"] == goal.module_path
        assert "teaching_assumption" in data["confirmed_topic"]["material_origins"]
        return {
            "accepted": True,
            "explanation": "代码严格大于分支明确，签名有效和 max_age 非空是教学前提，没有声称执行仓库",
        }
    source = data["sources"][0]
    assert source["version"] == snapshot.repository.commit
    return {
        "case": {
            "target": goal.goal.target.model_dump(),
            "catalog_version": CATALOG.version,
            "title": "为签名有效期补齐边界测试",
            "task": "选择能区分大于与等于边界的测试断言，并说明源码依据。",
            "assumptions": [
                "教学假设：签名已核验通过、时间戳格式有效、max_age=60、return_timestamp=False；没有执行目标代码。"
            ],
            "evidence": [
                {
                    "id": "e1",
                    "label": "教学材料",
                    "text": "教学假设：受控时钟让 age 恰为 60 秒，max_age 为 60 秒。",
                    "facts": {"age": "60", "max_age": "60"},
                    "citations": [{"source_id": source["id"], "quote": source["text"]}],
                }
            ],
            "judgments": [
                {
                    "id": "j1",
                    "kind": "choice",
                    "prompt": "基于这些前提，age=60 的边界测试应期待什么？",
                    "options": ["返回原值，不因过期抛错", "抛 SignatureExpired"],
                    "evidence_ids": ["e1"],
                }
            ],
            "rubric": [
                {
                    "judgment_id": "j1",
                    "acceptable_options": [0],
                    "reasoning": "源码使用 age > max_age，而非大于等于；等于边界且非负应返回原值。",
                    "evidence_ids": ["e1"],
                    "counterexample": "age=61 时大于 max_age，将抛 SignatureExpired；未来时间 age<0 也拒绝。",
                    "help_boundary": "直接说明等于不触发过期是方向性帮助",
                }
            ],
            "variation": {
                "causal_condition": "将 age 从60改61",
                "expected_evidence": "大于分支触发 SignatureExpired",
                "decision_effect": "从返回值断言改为异常断言",
            },
            "missing_evidence": [],
            "conflicts": [],
        },
        "materials": [{"evidence_id": "e1", "kind": "teaching_assumption"}],
    }


def test_real_public_source_to_original_feedback_record(provider, tmp_path):
    _, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    provider["candidate"] = respond
    body = begin(auth, config, public_material())
    process, _ = start_worker(tmp_path, provider, body["request_id"])
    try:
        topic = wait_topic(auth, body["topic_id"])
        assert topic["jobs"][0]["status"] == "completed", topic
        version = topic["versions"][0]
        path = f"/api/v1/topics/{body['topic_id']}"
        assert (
            client.post(
                path + "/confirm",
                headers=auth,
                json={"expected_version": version["id"]},
            ).status_code
            == 200
        )
        started = client.post(
            path + "/start",
            headers=auth,
            json={
                "request_id": str(uuid.uuid4()),
                "expected_version": version["id"],
                "node_id": version["nodes"][0]["id"],
                "expected_config_version": config["version"],
                "disclosure_accepted": True,
            },
        )
        assert started.status_code == 202, started.text
        run = wait_run(auth, started.json()["id"]).json()
        assert run["status"] == "completed", run
        answer = {
            "judgment_id": "j1",
            "value": 0,
            "reason": "源码是严格大于而非大于等于，60等于max_age不触发过期；61应断言异常。",
        }
        submitted = client.post(
            f"/api/v1/training/tasks/{run['id']}/submissions",
            headers=auth,
            json={
                "request_id": str(uuid.uuid4()),
                "answers": [answer],
                "expected_config_version": config["version"],
                "disclosure_accepted": True,
            },
        )
        assert submitted.status_code == 202
        assert wait_submission(auth, run["id"])["awarded_points"] == 10

        def grade(context):
            assert (
                context["sources"][0]["version"]
                == public_material()[0].repository.commit
            )
            result = grading(context)
            item = result["items"][0]
            item["grounding"][0].update(fact="age", value="60")
            item["reason_claims"][0]["interpreted_fact_value"] = "60"
            return result

        provider["grading"] = grade
        start_evaluation(auth, run["id"], config)
        assert wait_evaluation(auth, run["id"])["status"] == "completed"
        restored = client.get(
            f"/api/v1/project-training/{body['topic_id']}", headers=auth
        ).json()
        assert restored["topic"]["completed_node_ids"] == [version["nodes"][0]["id"]]
        assert (
            restored["current"]["repository"]["commit"]
            == public_material()[0].repository.commit
        )
    finally:
        stop_worker(process)
