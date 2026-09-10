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
        from tests.test_submissions import wait_submission

        submitted = client.post(
            f"/api/v1/training/tasks/{result['id']}/submissions",
            headers=auth,
            json={
                "request_id": str(uuid.uuid4()),
                "answers": [
                    {
                        "judgment_id": "j1",
                        "value": 0,
                        "reason": "确认可能丢失，不能仅凭未确认断定没有执行。",
                    }
                ],
                "expected_config_version": config["version"],
                "disclosure_accepted": True,
            },
        )
        assert submitted.status_code == 202, submitted.text
        assert wait_submission(auth, result["id"])["awarded_points"] == 10
        owner = uuid.UUID(client.get("/api/v1/users/me", headers=auth).json()["id"])
        update = {
            "request_id": str(uuid.uuid4()),
            "topic_id": str(uuid.uuid4()),
            "project_run_id": str(source(owner, config, material)),
            "previous_version_id": original["id"],
            "expected_active_version": original["id"],
            "expected_config_version": config["version"],
            "disclosure_accepted": True,
        }
        assert (
            client.post(
                "/api/v1/project-training/analyze", headers=auth, json=update
            ).status_code
            == 202
        )
        assert wait_topic(auth, update["topic_id"])["jobs"][0]["status"] == "completed"
        updated = public(auth, update["topic_id"])
        node = updated["current"]["route"]["nodes"][0]
        assert node["id"] == original["nodes"][0]["id"]
        assert node["id"] in updated["topic"]["completed_node_ids"]
        update_path = f"/api/v1/topics/{update['topic_id']}"
        reordered = client.post(
            update_path + "/edit",
            headers=auth,
            json={
                "expected_version": updated["current"]["route"]["id"],
                "operation": "reorder",
                "order": [node["id"]],
            },
        )
        assert reordered.status_code == 200
        assert (
            node["id"]
            in public(auth, update["topic_id"])["topic"]["completed_node_ids"]
        )
        changed = client.post(
            update_path + "/edit",
            headers=auth,
            json={
                "expected_version": reordered.json()["current"]["id"],
                "operation": "edit",
                "node_id": node["id"],
                "goal": {
                    "target": node["target"],
                    "text": node["text"],
                    "focus": "新的完整目标重点，不能猜测与旧完成相同",
                },
            },
        )
        assert changed.status_code == 200
        final = public(auth, update["topic_id"])
        assert (
            final["current"]["route"]["nodes"][0]["id"]
            not in final["topic"]["completed_node_ids"]
        )
        assert any(row["id"] == result["id"] for row in final["topic"]["runs"])
        assert wait_submission(auth, result["id"])["awarded_points"] == 10
    finally:
        stop_worker(worker)


def test_concurrent_family_confirmations_choose_one_current(material):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.model_config.service import lock_owner
    from app.project.training_service import link_update

    owner, auth = account()
    config = save(auth).json()
    root, old = seeded(owner, config, material)
    assert confirm(auth, root, old.route.id).status_code == 200
    candidates = [seeded(owner, config, material) for _ in range(2)]
    with Session(engine) as session:
        lock_owner(session, owner)
        for identity, _ in candidates:
            link_update(
                session,
                session.get(Topic, identity),
                old.route.id,
                material[0].repository,
                old.route.id,
            )
        session.commit()
    barrier = Barrier(2)

    def choose(candidate):
        identity, value = candidate
        barrier.wait(timeout=5)
        return confirm(auth, identity, value.route.id, old.route.id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(choose, candidates))
    assert sorted(response.status_code for response in responses) == [200, 409]
    winner = candidates[
        next(i for i, response in enumerate(responses) if response.status_code == 200)
    ][1].route.id
    for identity in [root, *(identity for identity, _ in candidates)]:
        assert public(auth, identity)["active"]["route"]["id"] == str(winner)
    assert public(auth, root)["current"]["route"]["id"] == str(old.route.id)


def test_stopped_route_requires_new_analysis_identity(material):
    from tests.test_project_training_api import begin

    _, auth = account()
    config = save(auth).json()
    body = begin(auth, config, material)
    path = f"/api/v1/topics/{body['topic_id']}/jobs/{body['request_id']}"
    stopped = client.post(path + "/stop", headers=auth)
    assert stopped.status_code == 200, stopped.text
    assert client.post(path + "/retry", headers=auth).status_code == 409
    restarted = {**body, "request_id": str(uuid.uuid4())}
    response = client.post(
        "/api/v1/project-training/analyze", headers=auth, json=restarted
    )
    assert response.status_code == 202, response.text
    jobs = {job["id"]: job for job in response.json()["topic"]["jobs"]}
    assert jobs[body["request_id"]]["status"] == "stopped"
    assert jobs[restarted["request_id"]]["status"] == "queued"
    assert (
        client.post(
            f"/api/v1/topics/{body['topic_id']}/jobs/{restarted['request_id']}/stop",
            headers=auth,
        ).status_code
        == 200
    )
