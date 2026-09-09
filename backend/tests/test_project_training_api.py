import json
import uuid

from sqlmodel import Session

from app.core.db import engine
from app.project.models import ProjectRun
from tests.test_accounts import client
from tests.test_evaluations import (
    grading,
)
from tests.test_evaluations import (
    start as start_evaluation,
)
from tests.test_evaluations import (
    wait as wait_evaluation,
)
from tests.test_model_config import account, save
from tests.test_project_training_rules import material as material
from tests.test_submissions import wait_submission
from tests.test_topics import wait_topic
from tests.test_training import candidate, start_worker, stop_worker, wait_run
from tests.test_training import provider as provider


def begin(auth, config, material):
    snapshot, mapped, goal = material
    owner = client.get("/api/v1/users/me", headers=auth).json()["id"]
    with Session(engine) as session:
        source = ProjectRun(
            user_id=uuid.UUID(owner),
            url="https://github.com/public-owner/project",
            config_version=uuid.UUID(config["version"]),
            destination=config["service_url"],
            model_id=config["model_id"],
            status="failed",
            code="partial_sources",
            snapshot=snapshot.model_dump(mode="json"),
            project_map=mapped.model_dump(mode="json"),
        )
        session.add(source)
        session.commit()
        source_id = source.id
    body = {
        "request_id": str(uuid.uuid4()),
        "topic_id": str(uuid.uuid4()),
        "project_run_id": str(source_id),
        "expected_config_version": config["version"],
        "disclosure_accepted": True,
    }
    response = client.post("/api/v1/project-training/analyze", headers=auth, json=body)
    assert response.status_code == 202, response.text
    return body


def response_for(material):
    snapshot, mapped, goal = material

    def respond(payload):
        data = json.loads(payload["messages"][1]["content"])
        if "context" in data:
            context = data["context"]
            assert "project_modules" in context
            assert "confirmed_modules" in context["project_modules"]
            return (
                {"accepted": True, "explanation": "受控检查模块目标与实际源码引用"}
                if "candidate" in context
                else {
                    "goals": [goal.model_dump(mode="json")],
                    "message": "从已读模块判断必要证据",
                }
            )
        assert data["confirmed_topic"]["module_path"] == goal.module_path
        assert data["sources"][0]["version"] == snapshot.repository.commit
        assert data["sources"][0]["text"] == goal.evidence[0].quote
        if "candidate" in data:
            assert "material_origins" in data["confirmed_topic"]
            return {
                "accepted": True,
                "explanation": "受控假设显式标注，源码片段定位保留",
            }
        case = candidate(payload)
        case["evidence"][0]["citations"][0]["source_id"] = data["sources"][0]["id"]
        case["evidence"][0]["text"] = "合成教学日志：确认未收到，执行结果尚需核对"
        return {
            "case": case,
            "materials": [{"evidence_id": "e1", "kind": "synthetic_log"}],
        }

    return respond


def test_project_frozen_route_actual_worker_and_private_case(
    provider, tmp_path, material
):
    _, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    snapshot, mapped, goal = material
    provider["candidate"] = response_for(material)
    body = begin(auth, config, material)
    process, _ = start_worker(tmp_path, provider, body["request_id"])
    try:
        final = wait_topic(auth, body["topic_id"])
        assert final["jobs"][0]["status"] == "completed", final
        path = f"/api/v1/topics/{body['topic_id']}"
        version = final["versions"][0]
        start = {
            "request_id": str(uuid.uuid4()),
            "expected_version": version["id"],
            "node_id": version["nodes"][0]["id"],
            "expected_config_version": config["version"],
            "disclosure_accepted": True,
        }
        assert client.post(path + "/start", headers=auth, json=start).status_code == 409
        assert (
            client.post(
                path + "/confirm",
                headers=auth,
                json={"expected_version": version["id"]},
            ).status_code
            == 200
        )
        response = client.post(path + "/start", headers=auth, json=start)
        assert response.status_code == 202, response.text
        result = wait_run(auth, response.json()["id"]).json()
        assert result["status"] == "completed", result
        assert result["project_materials"] == [
            {"evidence_id": "e1", "kind": "synthetic_log"}
        ]
        assert "HIDDEN_REASON" not in json.dumps(result)
        assert len(provider["requests"]) == 4

        def grade(context):
            assert context["sources"][0]["version"] == snapshot.repository.commit
            assert context["sources"][0]["text"] == goal.evidence[0].quote
            return grading(context)

        provider["grading"] = grade
        original = {
            "judgment_id": "j1",
            "value": 0,
            "reason": "确认可能丢失，不能仅凭未确认断定没有执行。",
        }
        submitted = client.post(
            f"/api/v1/training/tasks/{result['id']}/submissions",
            headers=auth,
            json={
                "request_id": str(uuid.uuid4()),
                "answers": [original],
                "expected_config_version": config["version"],
                "disclosure_accepted": True,
            },
        )
        assert submitted.status_code == 202, submitted.text
        assert wait_submission(auth, result["id"])["awarded_points"] == 10
        start_evaluation(auth, result["id"], config)
        assessed = wait_evaluation(auth, result["id"])
        assert assessed["status"] == "completed", assessed
        _, stranger = account()
        assert (
            client.get(
                f"/api/v1/project-training/{body['topic_id']}", headers=stranger
            ).status_code
            == 404
        )
        assert client.get("/api/v1/topics", headers=auth).json() == []
    finally:
        stop_worker(process)
