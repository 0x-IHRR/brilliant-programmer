import time
import uuid

import pytest
from sqlalchemy import text
from sqlmodel import Session

from app.core.db import engine
from app.project.models import ProjectRun
from app.training.topic_models import TopicJob
from tests.test_accounts import client
from tests.test_model_config import account, save
from tests.test_project_training_api import begin, response_for
from tests.test_project_training_rules import material as material
from tests.test_topics import wait_topic
from tests.test_training import provider as provider
from tests.test_training import start_worker, stop_worker


@pytest.fixture
def route_ready(provider, tmp_path, material):
    _, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    provider["candidate"] = response_for(material)
    body = begin(auth, config, material)
    process, _ = start_worker(tmp_path, provider, body["request_id"])
    try:
        topic = wait_topic(auth, body["topic_id"])
        assert topic["jobs"][0]["status"] == "completed", topic
        yield auth, config, body, topic
    finally:
        stop_worker(process)


def test_project_route_cas_frozen_sources_and_config_free_read(route_ready, provider):
    auth, config, body, topic = route_ready
    path = f"/api/v1/topics/{body['topic_id']}"
    version = topic["versions"][0]
    project_path = f"/api/v1/project-training/{body['topic_id']}"
    frozen = client.get(project_path, headers=auth).json()["current"]
    with Session(engine) as session:
        source = session.get(ProjectRun, uuid.UUID(body["project_run_id"]))
        source.snapshot = {**source.snapshot, "fragments": []}
        source.project_map = {
            "confirmed": [],
            "unverified": [],
            "missing": ["later read failed"],
        }
        session.add(source)
        session.commit()
    assert client.get(project_path, headers=auth).json()["current"] == frozen
    same = client.post("/api/v1/project-training/analyze", headers=auth, json=body)
    assert same.status_code == 202 and len(provider["requests"]) == 2
    goal = {k: v for k, v in version["nodes"][0].items() if k != "id"}
    goal["focus"] = "先查代码中的条件，再核对还缺少的运行证据"
    edited = client.post(
        path + "/edit",
        headers=auth,
        json={
            "expected_version": version["id"],
            "operation": "edit",
            "node_id": version["nodes"][0]["id"],
            "goal": goal,
        },
    )
    assert edited.status_code == 200, edited.text
    current = client.get(project_path, headers=auth).json()["current"]
    assert current["bindings"][0]["references"] == frozen["bindings"][0]["references"]
    assert current["route"]["nodes"][0]["id"] != version["nodes"][0]["id"]
    assert (
        client.post(
            path + "/confirm", headers=auth, json={"expected_version": version["id"]}
        ).status_code
        == 409
    )
    assert (
        client.post(
            path + "/edit",
            headers=auth,
            json={
                "expected_version": version["id"],
                "operation": "edit",
                "node_id": version["nodes"][0]["id"],
                "goal": goal,
            },
        ).status_code
        == 409
    )
    deleted = client.delete(
        "/api/v1/model-config",
        headers=auth,
        params={"expected_version": config["version"]},
    )
    assert deleted.status_code == 204
    restored = client.get(project_path, headers=auth)
    assert restored.status_code == 200 and restored.json()["current"] == current
    assert (
        client.post(
            "/api/v1/topics/analyze",
            headers=auth,
            json={
                "request_id": str(uuid.uuid4()),
                "topic_id": body["topic_id"],
                "input_text": "replace project with ordinary",
                "expected_config_version": config["version"],
                "disclosure_accepted": True,
            },
        ).status_code
        == 409
    )


def test_project_provenance_database_immutable(route_ready):
    _, _, body, topic = route_ready
    rows = [
        ("project_topic", "topic_id", body["topic_id"]),
        ("project_training_input", "id", body["request_id"]),
        ("project_training_version", "version_id", topic["versions"][0]["id"]),
    ]
    for table, field, identity in rows:
        for sql in (
            f"UPDATE {table} SET {field}={field} WHERE {field}=:id",
            f"DELETE FROM {table} WHERE {field}=:id",
        ):
            with (
                Session(engine) as session,
                pytest.raises(Exception, match="immutable"),
            ):
                session.execute(text(sql), {"id": uuid.UUID(identity)})


def test_missing_module_evidence_does_not_generate(provider, tmp_path, material):
    snapshot, mapped, goal = material
    incomplete = (
        snapshot,
        mapped,
        goal.model_copy(
            update={"evidence": (), "missing": ("未读到本模块关键处理分支",)}
        ),
    )
    _, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    provider["candidate"] = response_for(incomplete)
    body = begin(auth, config, incomplete)
    process, _ = start_worker(tmp_path, provider, body["request_id"])
    try:
        topic = wait_topic(auth, body["topic_id"])
        assert topic["jobs"][0]["status"] == "completed"
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
        assert started.status_code == 409 and "未读到本模块关键处理分支" in started.text
        assert len(provider["requests"]) == 2
        assert client.get(path, headers=auth).json()["runs"] == []
    finally:
        stop_worker(process)


def test_project_route_stop_new_analysis_preserves_input_and_received_usage(
    provider, tmp_path, material
):
    _, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    provider["candidate"] = response_for(material)
    provider["mode"] = "partial_usage"
    body = begin(auth, config, material)
    process, control = start_worker(
        tmp_path, provider, body["request_id"], observe_usage=True
    )
    try:
        marker = type(control)(str(control) + ".usage_received")
        deadline = time.monotonic() + 15
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists(), "consumer did not receive usage"
        root = f"/api/v1/topics/{body['topic_id']}/jobs/{body['request_id']}"
        stopped = client.post(root + "/stop", headers=auth)
        assert stopped.status_code == 200
        assert stopped.json()["jobs"][0]["status"] == "stopped"
        assert (
            client.get(
                f"/api/v1/project-training/{body['topic_id']}", headers=auth
            ).json()["current"]
            is None
        )
        assert len(provider["requests"]) == 1
        provider["release"].set()
        provider["mode"] = "ok"
        assert client.post(root + "/retry", headers=auth).status_code == 409
        replacement = {**body, "request_id": str(uuid.uuid4())}
        assert (
            client.post(
                "/api/v1/project-training/analyze", headers=auth, json=replacement
            ).status_code
            == 202
        )
        final = wait_topic(auth, body["topic_id"])
        jobs = {job["id"]: job for job in final["jobs"]}
        assert jobs[replacement["request_id"]]["status"] == "completed", final
        assert jobs[body["request_id"]]["status"] == "stopped", final
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            calls = client.get("/api/v1/model-config/usage", headers=auth).json()[
                "calls"
            ]
            if len(calls) == 3 and all(
                c["code"] == "ok"
                for c in calls
                if c["task_id"] == replacement["request_id"]
            ):
                break
            time.sleep(0.01)
        assert len(calls) == 3 and len(provider["requests"]) == 3
        first = next(c for c in calls if c["task_id"] == body["request_id"])
        assert (
            first["prompt_tokens"] == 11
            and first["completion_tokens"] is None
            and first["total_tokens"] == 20
        )
        assert all(
            c["code"] == "ok"
            for c in calls
            if c["task_id"] == replacement["request_id"]
        )
        assert (
            client.post(
                "/api/v1/project-training/analyze", headers=auth, json=body
            ).status_code
            == 202
        )
        assert len(provider["requests"]) == 3
    finally:
        stop_worker(process)


@pytest.mark.parametrize("failure", ["quote", "module", "rejected", "authentication"])
def test_project_analysis_rejects_unusable_results_without_public_route(
    provider, tmp_path, material, failure
):
    _, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    normal = response_for(material)

    def reply(payload):
        result = normal(payload)
        if failure == "quote" and "goals" in result:
            result["goals"][0]["evidence"][0]["quote"] = (
                "not present in the actual retained source"
            )
        if failure == "module" and "goals" in result:
            result["goals"][0]["module_path"] = "unread/invented.py"
        if failure == "rejected" and "accepted" in result:
            result["accepted"] = False
            result["explanation"] = "本模块来源不足以支持推荐目标，不以标签代替实际内容"
        return result

    provider["candidate"] = reply
    if failure == "authentication":
        provider["mode"] = "auth"
    body = begin(auth, config, material)
    process, _ = start_worker(tmp_path, provider, body["request_id"])
    try:
        topic = wait_topic(auth, body["topic_id"])
        assert topic["jobs"][0]["status"] == "failed", topic
        assert topic["current"] is None and topic["runs"] == []
        assert len(provider["requests"]) == (2 if failure == "rejected" else 1)
        if failure == "authentication":
            with Session(engine) as session:
                job = session.get(TopicJob, uuid.UUID(body["request_id"]))
                assert job is not None and job.code == "authentication"
            result = client.post(
                f"/api/v1/topics/{body['topic_id']}/jobs/{body['request_id']}/retry",
                headers=auth,
            )
            assert result.status_code == 409
            assert len(provider["requests"]) == 1
    finally:
        stop_worker(process)


def test_project_ordinary_allowed_but_failed_quality_blocks_independent(
    route_ready, provider
):
    from app.training.models import TrainingRun
    from app.training.schema import Source
    from app.training.topic_models import Topic
    from tests.test_quality_api import publish, report_for
    from tests.test_training import wait_run

    auth, config, body, topic = route_ready
    frozen = client.get(
        f"/api/v1/project-training/{body['topic_id']}", headers=auth
    ).json()["current"]
    sources = [
        Source.model_validate(reference["source"])
        for reference in frozen["bindings"][0]["references"]
    ]
    with Session(engine) as session:
        owner = session.get(Topic, uuid.UUID(body["topic_id"])).user_id
    report, _ = report_for(owner, config, failed=True, sources=sources)
    publish(report)
    version = topic["current"]
    path = f"/api/v1/topics/{body['topic_id']}"
    assert (
        client.post(
            path + "/confirm", headers=auth, json={"expected_version": version["id"]}
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
    run_id = started.json()["id"]
    original = wait_run(auth, run_id).json()
    assert original["status"] == "completed" and original["current_mode"] == "practice"
    before = len(provider["requests"])
    attempt = uuid.uuid4()
    result = client.post(
        f"/api/v1/training/tasks/{run_id}/independent",
        headers=auth,
        json={
            "request_id": str(attempt),
            "expected_config_version": config["version"],
            "disclosure_accepted": True,
        },
    )
    assert result.status_code == 409 and "未达标" in result.json()["detail"]
    with Session(engine) as session:
        assert session.get(TrainingRun, attempt) is None
    assert len(provider["requests"]) == before == 4
    assert (
        client.get(f"/api/v1/training/tasks/{run_id}", headers=auth).json()["case"]
        == original["case"]
    )
