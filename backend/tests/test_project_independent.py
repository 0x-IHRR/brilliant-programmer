import json
import uuid

from sqlmodel import Session

from app.core.db import engine
from app.training.models import TrainingRun
from app.training.schema import Candidate
from tests.test_accounts import client
from tests.test_concepts import coach, publish, receipt
from tests.test_concepts import request as request_help
from tests.test_concepts import wait as wait_help
from tests.test_independent_api import confirmed_publication
from tests.test_model_config import account, save
from tests.test_practices import guided_coach
from tests.test_project_training_api import begin, response_for
from tests.test_project_training_rules import material as material
from tests.test_topics import wait_topic
from tests.test_training import provider as provider
from tests.test_training import start_worker, stop_worker, wait_run


def test_project_independent_uses_actual_sources_and_full_comparison_then_help(
    provider, tmp_path, material
):
    _, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    provider["candidate"] = response_for(material)
    body = begin(auth, config, material)
    process, _ = start_worker(tmp_path, provider, body["request_id"])
    try:
        topic = wait_topic(auth, body["topic_id"])
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
        assert started.status_code == 202
        original = wait_run(auth, started.json()["id"]).json()
        assert original["status"] == "completed"
        with Session(engine) as session:
            old = session.get(TrainingRun, uuid.UUID(original["id"]))
            old_case = Candidate.model_validate(old.candidate)
            sources = old.sources
        new = old_case.model_dump(mode="json")
        new["evidence"][0]["facts"]["confirmed"] = "true"
        new["evidence"][0]["text"] = "合成教学日志：受控情境已收到提交完成确认。"
        new["judgments"][0]["options"][0] = "保留已确认完成的结果，不重执行"
        new["rubric"][0]["reasoning"] = (
            "已有提交完成确认，重复执行可能产生重复结果，应保留。"
        )
        new["variation"] = {
            "causal_condition": "收到明确提交完成确认",
            "expected_evidence": "已完成确认记录",
            "decision_effect": "从补证改为保留已完成结果",
        }
        comparison = {
            "seen_run_id": original["id"],
            "seen_judgment_id": "j1",
            "new_judgment_id": "j1",
            "relation": "different_causal_scenario",
            "changes": [
                {
                    "dimension": "causal_condition",
                    "before": {
                        "evidence_id": "e1",
                        "fact": "confirmed",
                        "value": "false",
                    },
                    "after": {
                        "evidence_id": "e1",
                        "fact": "confirmed",
                        "value": "true",
                    },
                    "before_variation": old_case.variation.causal_condition,
                    "after_variation": new["variation"]["causal_condition"],
                    "before_reasoning": old_case.rubric[0].reasoning,
                    "after_reasoning": new["rubric"][0]["reasoning"],
                    "before_consequence": old_case.judgments[0].options[0],
                    "after_consequence": new["judgments"][0]["options"][0],
                    "effect": "different_decision",
                    "explanation": "未确认仍需核对；已经确认后应避免重复执行。",
                }
            ],
        }

        def reply(payload):
            data = json.loads(payload["messages"][1]["content"])
            assert data["sources"] == sources
            if "new" in data:
                assert (
                    len(data["seen"]) == 1
                    and data["seen"][0]["run_id"] == original["id"]
                )
                assert "material_origins" in data["confirmed_topic"]
                return {
                    "comparisons": [comparison],
                    "topic_coverage": {
                        "accepted": True,
                        "explanation": "实际判断仍是确认与执行，引用同一冻结代码；情境变化明确标为合成",
                    },
                }
            assert data["confirmed_topic"]["module_path"] == material[2].module_path
            return {
                "case": new,
                "materials": [{"evidence_id": "e1", "kind": "synthetic_log"}],
            }

        provider["candidate"] = reply
        independent = client.post(
            f"/api/v1/training/tasks/{original['id']}/independent",
            headers=auth,
            json={
                "request_id": str(uuid.uuid4()),
                "expected_config_version": config["version"],
                "disclosure_accepted": True,
            },
        )
        assert independent.status_code == 202, independent.text
        result = wait_run(auth, independent.json()["id"]).json()
        assert result["status"] == "completed", result
        assert result["launch_mode"] == "independent"
        assert result["project_materials"] == [
            {"evidence_id": "e1", "kind": "synthetic_log"}
        ]
        provider["coach"] = coach
        help_item, _ = request_help(auth, result["id"], config)
        ready = wait_help(auth, result["id"], help_item["id"])
        assert ready["status"] == "ready", ready
        publication = publish(auth, result["id"], help_item["id"])
        assert receipt(auth, result["id"], publication).status_code == 200
        assert (
            client.get(f"/api/v1/training/tasks/{result['id']}", headers=auth).json()[
                "current_mode"
            ]
            == "independent"
        )
        provider["coach"] = guided_coach
        directional = confirmed_publication((auth, result["id"], config))
        assert receipt(auth, result["id"], directional).status_code == 200
        assert (
            client.get(f"/api/v1/training/tasks/{result['id']}", headers=auth).json()[
                "current_mode"
            ]
            == "practice"
        )
        restored = client.get(
            f"/api/v1/training/tasks/{original['id']}", headers=auth
        ).json()
        assert restored["case"] == original["case"]
    finally:
        stop_worker(process)
