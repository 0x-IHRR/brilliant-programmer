"""Actual owner/CAS transactions; source fixtures are not semantic certification."""

import uuid

import pytest
from sqlmodel import Session

from app.core.db import engine
from app.project.models import ProjectRun
from app.project.training_models import ProjectInput, ProjectTopic
from app.project.training_rules import propose
from app.project.training_service import accept
from app.project.training_service import save as save_route
from app.project.worker import pin
from app.training.topic_models import Topic, TopicJob
from tests.test_accounts import client
from tests.test_model_config import account, save
from tests.test_project_training_rules import material as material
from tests.test_training import provider as provider


def source(owner, config, material, **changes):
    snapshot, mapped, _ = material
    with Session(engine) as session:
        row = ProjectRun(
            user_id=owner,
            url="https://github.com/public-owner/project",
            config_version=uuid.UUID(config["version"]),
            destination=config["service_url"],
            model_id=config["model_id"],
            repository_key="public-owner/project",
            commit=snapshot.repository.commit,
            status="completed",
            snapshot=snapshot.model_dump(mode="json"),
            project_map=mapped.model_dump(mode="json"),
            **changes,
        )
        session.add(row)
        session.commit()
        return row.id


def seeded(owner, config, material):
    source_id = source(owner, config, material)
    snapshot, mapped, goal = material
    value = propose(source_id, snapshot, mapped, (goal,), key="")
    with Session(engine) as session:
        topic = Topic(user_id=owner)
        session.add(topic)
        session.flush()
        session.add(ProjectTopic(topic_id=topic.id, project_run_id=source_id))
        job = TopicJob(
            id=uuid.uuid4(),
            user_id=owner,
            topic_id=topic.id,
            input_text="synthetic",
            config_version=uuid.UUID(config["version"]),
            destination=config["service_url"],
            model_id=config["model_id"],
            status="completed",
        )
        session.add(job)
        session.flush()
        session.add(
            ProjectInput(
                id=job.id,
                topic_id=topic.id,
                project_run_id=source_id,
                snapshot=snapshot.model_dump(mode="json"),
                project_map=mapped.model_dump(mode="json"),
            )
        )
        session.flush()
        save_route(session, topic, value, job.id)
        session.commit()
        return topic.id, value


def confirm(auth, topic, version, active=None):
    return client.post(
        f"/api/v1/topics/{topic}/confirm",
        headers=auth,
        json={
            "expected_version": str(version),
            "expected_active_version": str(active) if active else None,
        },
    )


def public(auth, topic):
    response = client.get(f"/api/v1/project-training/{topic}", headers=auth)
    assert response.status_code == 200
    return response.json()


def test_updated_source_keeps_old_active_and_confirmation_cas(material):
    owner, auth = account()
    config = save(auth).json()
    old_topic, old = seeded(owner, config, material)
    assert confirm(auth, old_topic, old.route.id).status_code == 200
    old_state = public(auth, old_topic)
    # Reanalysis is a new acquisition identity but the same exact source/goal.
    new_source = source(owner, config, material)
    body = {
        "request_id": str(uuid.uuid4()),
        "topic_id": str(uuid.uuid4()),
        "project_run_id": str(new_source),
        "previous_version_id": str(old.route.id),
        "expected_active_version": str(old.route.id),
        "expected_config_version": config["version"],
        "disclosure_accepted": True,
    }
    started = client.post("/api/v1/project-training/analyze", headers=auth, json=body)
    assert started.status_code == 202, started.text
    topic_id = uuid.UUID(body["topic_id"])
    before = public(auth, topic_id)
    assert before["current"] is None and before["active"]["route"]["id"] == str(
        old.route.id
    )
    with Session(engine) as session:
        from app.model_config.service import lock_owner

        lock_owner(session, owner)
        topic = session.get(Topic, topic_id)
        job = session.get(TopicJob, uuid.UUID(body["request_id"]))
        accept(
            session,
            topic,
            job,
            __import__("json").dumps(
                {"goals": [material[2].model_dump(mode="json")], "message": "synthetic"}
            ),
        )
        accept(
            session,
            topic,
            job,
            '{"accepted":true,"explanation":"controlled content check"}',
        )
        session.commit()
    candidate = public(auth, topic_id)["current"]["route"]
    assert candidate["nodes"][0]["id"] == str(old.route.nodes[0].id)
    assert confirm(auth, topic_id, candidate["id"], uuid.uuid4()).status_code == 409
    assert public(auth, topic_id)["active"]["route"]["id"] == str(old.route.id)
    assert confirm(auth, topic_id, candidate["id"], old.route.id).status_code == 200
    assert public(auth, old_topic)["active"]["route"]["id"] == candidate["id"]
    assert public(auth, old_topic)["current"] == old_state["current"]
    assert confirm(auth, old_topic, old.route.id, old.route.id).status_code == 409
    # An already committed confirmation is idempotent despite its old CAS token.
    assert confirm(auth, topic_id, candidate["id"], old.route.id).status_code == 200


@pytest.mark.parametrize("kind", ["owner", "scope", "unconfirmed"])
def test_update_rejects_wrong_predecessor(material, kind):
    owner, auth = account()
    config = save(auth).json()
    topic, old = seeded(owner, config, material)
    if kind != "unconfirmed":
        assert confirm(auth, topic, old.route.id).status_code == 200
    target = material
    if kind == "scope":
        snapshot, mapped, goal = material
        target = (
            snapshot.model_copy(
                update={
                    "repository": snapshot.repository.model_copy(
                        update={"focus": "src/other.py"}
                    )
                }
            ),
            mapped,
            goal,
        )
    if kind == "owner":
        owner, auth = account()
        config = save(auth).json()
    identity = source(owner, config, target)
    body = {
        "request_id": str(uuid.uuid4()),
        "topic_id": str(uuid.uuid4()),
        "project_run_id": str(identity),
        "previous_version_id": str(old.route.id),
        "expected_active_version": str(old.route.id),
        "expected_config_version": config["version"],
        "disclosure_accepted": True,
    }
    assert client.post(
        "/api/v1/project-training/analyze", headers=auth, json=body
    ).status_code in {404, 409}
    with Session(engine) as session:
        assert session.get(Topic, uuid.UUID(body["topic_id"])) is None


def test_same_commit_reuse_requires_exact_read_scope(material):
    owner, auth = account()
    config = save(auth).json()
    old_id = source(owner, config, material)
    snapshot, mapped, goal = material
    different = snapshot.model_copy(
        update={
            "repository": snapshot.repository.model_copy(
                update={"focus": "src/app.py", "start_line": 2, "end_line": 2}
            )
        }
    )
    new_id = source(owner, config, (different, mapped, goal))
    assert pin(new_id, different) is False
    same_id = source(owner, config, material)
    assert pin(same_id, snapshot) is True
    with Session(engine) as session:
        assert session.get(ProjectRun, same_id).reused_from_id == old_id
        assert session.get(ProjectRun, old_id).snapshot == snapshot.model_dump(
            mode="json"
        )


def test_same_route_candidate_preserves_confirmed_generation(
    provider, tmp_path, material
):
    from tests.test_project_training_api import begin, response_for
    from tests.test_topics import wait_topic
    from tests.test_training import start_worker, stop_worker, wait_run

    _, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    provider["candidate"] = response_for(material)
    body = begin(auth, config, material)
    worker, _ = start_worker(tmp_path, provider, body["request_id"])
    try:
        state = wait_topic(auth, body["topic_id"])
        assert state["jobs"][0]["status"] == "completed", state
        original = state["versions"][0]
        path = f"/api/v1/topics/{body['topic_id']}"
        assert confirm(auth, body["topic_id"], original["id"]).status_code == 200
        changed_goal = {
            key: value for key, value in original["nodes"][0].items() if key != "id"
        }
        changed_goal["focus"] = "另一个尚未确认的重点，不应进入当前已确认题目"
        edited = client.post(
            path + "/edit",
            headers=auth,
            json={
                "expected_version": original["id"],
                "operation": "edit",
                "node_id": original["nodes"][0]["id"],
                "goal": changed_goal,
            },
        )
        assert edited.status_code == 200, edited.text
        candidate_id = edited.json()["current"]["id"]
        assert candidate_id != original["id"]
        current = public(auth, body["topic_id"])
        assert current["active"]["route"]["id"] == original["id"]
        request = {
            "request_id": str(uuid.uuid4()),
            "expected_version": original["id"],
            "node_id": original["nodes"][0]["id"],
            "expected_config_version": config["version"],
            "disclosure_accepted": True,
        }
        started = client.post(path + "/start", headers=auth, json=request)
        assert started.status_code == 202, started.text
        result = wait_run(auth, started.json()["id"]).json()
        assert result["status"] == "completed", result
        with Session(engine) as session:
            from app.training.models import TrainingRun

            run = session.get(TrainingRun, uuid.UUID(result["id"]))
            assert run.selection["topic_version_id"] == original["id"]
            assert run.selection["focus"] == original["nodes"][0]["focus"]
        assert public(auth, body["topic_id"])["current"]["route"]["id"] == candidate_id
        assert len(provider["requests"]) == 4
    finally:
        stop_worker(worker)
