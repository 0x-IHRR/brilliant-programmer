import json
import time
import uuid

import pytest
from sqlmodel import Session

from app.core.db import engine
from app.training.models import TrainingRun
from app.training.topic_models import Topic, TopicVersion
from app.training.topic_rules import Analysis, Goal, propose
from tests.test_accounts import client
from tests.test_model_config import account, save
from tests.test_training import candidate, start_worker, stop_worker, wait_run
from tests.test_training import provider as provider

TARGET = {
    "capability_id": "network.delivery",
    "difficulty": "基础",
    "background_id": "network-evidence-v1",
}


def interpretation(text="判断请求超时后可否重试", count=1):
    return {
        "kind": "clear" if count == 1 else "broad",
        "message": "先比较确认丢失与执行证据",
        "goals": [
            {
                "target": TARGET,
                "text": text + str(i),
                "focus": "区分确认与执行，要求补证",
            }
            for i in range(count)
        ],
        "recommended_index": 0,
    }


def controlled(payload):
    context = json.loads(payload["messages"][1]["content"])
    if "context" in context:
        if "candidate" in context["context"]:
            return {
                "accepted": True,
                "explanation": "目标与用户要求的重试证据一致，明确单判断",
            }
        return (
            interpretation(count=3)
            if context["context"]["input"] in {"网络路线", "网络路线下一段"}
            else interpretation()
        )
    if "confirmed_topic" in context and "candidate" in context:
        return {
            "accepted": True,
            "explanation": "题目判断确认丢失不能证明未执行，来源支持该判断",
        }
    return candidate(payload)


def begin(auth, config, **changes):
    body = {
        "request_id": str(uuid.uuid4()),
        "topic_id": str(uuid.uuid4()),
        "input_text": "想学请求超时后怎样重试",
        "expected_config_version": config["version"],
        "disclosure_accepted": True,
    } | changes
    response = client.post("/api/v1/topics/analyze", headers=auth, json=body)
    assert response.status_code == 202, response.text
    return body, response.json()


def wait_topic(auth, identity):
    end = time.monotonic() + 15
    while time.monotonic() < end:
        result = client.get(f"/api/v1/topics/{identity}", headers=auth).json()
        if all(
            job["status"] in {"completed", "failed", "stopped"}
            for job in result["jobs"]
        ):
            return result
        time.sleep(0.05)
    raise AssertionError(result)


def test_real_analysis_confirm_target_generation_and_usage(provider, tmp_path):
    _, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    provider["candidate"] = controlled
    body, topic = begin(auth, config)
    process, _ = start_worker(tmp_path, provider, body["request_id"])
    try:
        topic = wait_topic(auth, topic["id"])
        assert topic["current"], topic
        assert topic["active_id"] is None and topic["runs"] == []
        assert len(provider["requests"]) == 2
        version = topic["current"]
        node = version["nodes"][0]
        start = {
            "request_id": str(uuid.uuid4()),
            "expected_version": version["id"],
            "node_id": node["id"],
            "expected_config_version": config["version"],
            "disclosure_accepted": True,
        }
        url = f"/api/v1/topics/{topic['id']}"
        assert client.post(url + "/start", headers=auth, json=start).status_code == 409
        assert (
            client.post(
                url + "/confirm", headers=auth, json={"expected_version": version["id"]}
            ).status_code
            == 200
        )
        response = client.post(url + "/start", headers=auth, json=start)
        assert response.status_code == 202, response.text
        result = wait_run(auth, response.json()["id"]).json()
        assert result["case"], result
        assert len(provider["requests"]) == 4
        outgoing = json.loads(provider["requests"][2]["messages"][1]["content"])
        assert outgoing["confirmed_topic"] == {
            "goal": node["text"],
            "focus": node["focus"],
        }
        assert outgoing["observable_goal"] == node["text"]
        assert (
            client.post(url + "/start", headers=auth, json=start).json()["id"]
            == result["id"]
        )
        usage = client.get("/api/v1/model-config/usage", headers=auth).json()["calls"]
        assert len(usage) == 4 and sum(c["kind"] == "topic" for c in usage) == 2
        assert all(c["total_tokens"] is not None for c in usage)
        with Session(engine) as session:
            run = session.get(TrainingRun, uuid.UUID(result["id"]))
            assert (
                run.formal_submitted_at is None
                and run.recommendation_delivered_at is None
            )
    finally:
        stop_worker(process)


def seed_route(owner):
    first = propose("网络起步", Analysis.model_validate(interpretation(count=3)))
    expanded = propose(
        "接下来一段",
        Analysis.model_validate(interpretation("新判断", 3)),
        previous=first,
        expected_version=first.id,
        expand=True,
    )
    with Session(engine) as session:
        item = Topic(user_id=owner, current_id=expanded.id, active_id=first.id)
        session.add(item)
        session.flush()
        for row in (first, expanded):
            session.add(
                TopicVersion(
                    id=row.id, topic_id=item.id, snapshot=row.model_dump(mode="json")
                )
            )
        session.commit()
        return str(item.id), first, expanded


def test_six_node_local_edit_reorder_conflict_history_and_owner():
    owner, auth = account()
    _, other = account()
    identity, first, old = seed_route(owner)
    url = f"/api/v1/topics/{identity}"
    assert client.get(url, headers=other).status_code == 404
    body = {
        "expected_version": str(old.id),
        "operation": "edit",
        "node_id": str(old.nodes[3].id),
        "goal": Goal(
            **(old.nodes[3].model_dump(exclude={"id"}) | {"focus": "追加验证执行日志"})
        ).model_dump(mode="json"),
    }
    result = client.post(url + "/edit", headers=auth, json=body)
    assert result.status_code == 200, result.text
    value = result.json()
    current = value["current"]
    assert len(current["nodes"]) == 6
    assert value["active_id"] == str(first.id)
    assert current["nodes"][3]["id"] != str(old.nodes[3].id)
    assert current["nodes"][2]["id"] == str(old.nodes[2].id)
    assert client.post(url + "/edit", headers=auth, json=body).status_code == 409
    ids = [n["id"] for n in current["nodes"]][::-1]
    result = client.post(
        url + "/edit",
        headers=auth,
        json={"expected_version": current["id"], "operation": "reorder", "order": ids},
    )
    assert result.status_code == 200, result.text
    assert [n["id"] for n in result.json()["current"]["nodes"]] == ids
    assert len(result.json()["versions"]) == 4
    assert next(
        v for v in result.json()["versions"] if v["id"] == str(old.id)
    ) == old.model_dump(mode="json")


def test_inspection_refuses_misleading_analysis_and_keeps_input(provider, tmp_path):
    _, auth = account()
    config = save(auth, service_url=provider["url"]).json()

    def response(payload):
        context = json.loads(payload["messages"][1]["content"])
        if "candidate" in context.get("context", {}):
            return {
                "accepted": False,
                "explanation": "候选虽然自报clear但实际上没有响应工程问题",
            }
        return interpretation("偏离问题的目标")

    provider["candidate"] = response
    body, topic = begin(auth, config)
    process, _ = start_worker(tmp_path, provider, body["request_id"])
    try:
        topic = wait_topic(auth, topic["id"])
        assert topic["current"] is None and topic["runs"] == []
        assert topic["jobs"][0]["status"] == "failed"
        assert topic["jobs"][0]["input_text"] == body["input_text"]
        usage = client.get("/api/v1/model-config/usage", headers=auth).json()["calls"]
        assert len(usage) == 2 and all(row["total_tokens"] is not None for row in usage)
    finally:
        stop_worker(process)


def test_stop_then_retry_old_finish_cannot_fail_new_job():
    from app.training.topic_worker import finish

    _, auth = account()
    config = save(auth).json()
    body, topic = begin(auth, config)
    from app.training.topic_models import TopicJob

    with Session(engine) as session:
        old_job = session.get(TopicJob, uuid.UUID(body["request_id"])).queue_job_id
    url = f"/api/v1/topics/{topic['id']}/jobs/{body['request_id']}"
    assert client.post(url + "/stop", headers=auth).status_code == 200
    assert client.post(url + "/retry", headers=auth).status_code == 200
    finish(
        uuid.UUID(body["request_id"]),
        "internal_failure",
        "old attempt failure",
        old_job,
    )
    state = client.get(f"/api/v1/topics/{topic['id']}", headers=auth).json()
    assert state["jobs"][0]["status"] == "queued"
    assert client.post(url + "/stop", headers=auth).status_code == 200


def test_empty_unresolved_no_edit_or_start():
    owner, auth = account()
    config = save(auth).json()
    response = client.post(
        "/api/v1/topics/analyze",
        headers=auth,
        json={
            "request_id": str(uuid.uuid4()),
            "topic_id": str(uuid.uuid4()),
            "input_text": "  ",
            "expected_config_version": config["version"],
            "disclosure_accepted": True,
        },
    )
    assert response.status_code == 422
    candidate = propose(
        "天气如何",
        Analysis(
            kind="non_engineering", message="这里练工程判断，可改写想练的工程问题"
        ),
    )
    with Session(engine) as session:
        item = Topic(user_id=owner, current_id=candidate.id)
        session.add(item)
        session.flush()
        session.add(
            TopicVersion(
                id=candidate.id,
                topic_id=item.id,
                snapshot=candidate.model_dump(mode="json"),
            )
        )
        session.commit()
        identity = item.id
    assert (
        client.post(
            f"/api/v1/topics/{identity}/edit",
            headers=auth,
            json={
                "expected_version": str(candidate.id),
                "operation": "reorder",
                "order": [],
            },
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/topics/{identity}/confirm",
            headers=auth,
            json={"expected_version": str(candidate.id)},
        ).status_code
        == 409
    )


def test_accept_and_edit_serialize_under_owner_lock(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from sqlalchemy import text

    from app.training import topic_worker
    from app.training.topic_models import TopicJob

    owner, auth = account()
    config = save(auth).json()
    identity, _, old = seed_route(owner)
    with Session(engine) as session:
        job = TopicJob(
            id=uuid.uuid4(),
            user_id=owner,
            topic_id=uuid.UUID(identity),
            expected_version=old.id,
            input_text="更新目标",
            config_version=uuid.UUID(config["version"]),
            destination=config["service_url"],
            model_id=config["model_id"],
            stage="inspect",
            candidate=interpretation(),
            queue_job_id=123456,
            status="running",
        )
        session.add(job)
        session.commit()
        job_id = job.id
    entered, release = Event(), Event()
    original = topic_worker.save_version

    def blocked(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(topic_worker, "save_version", blocked)
    with ThreadPoolExecutor(2) as pool:
        accept = pool.submit(
            topic_worker.accept,
            job_id,
            json.dumps({"accepted": True, "explanation": "controlled matching target"}),
            123456,
        )
        assert entered.wait(3)
        edit = pool.submit(
            client.post,
            f"/api/v1/topics/{identity}/edit",
            headers=auth,
            json={
                "expected_version": str(old.id),
                "operation": "reorder",
                "order": [str(n.id) for n in old.nodes][::-1],
            },
        )
        try:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                with Session(engine) as session:
                    if session.execute(
                        text(
                            "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE wait_event_type='Lock' AND query LIKE '%FOR UPDATE%')"
                        )
                    ).scalar():
                        break
                time.sleep(0.02)
            else:
                raise AssertionError("expected real PostgreSQL lock waiter")
            assert not edit.done()
        finally:
            release.set()
        assert accept.result() is True
        assert edit.result().status_code == 409
    with Session(engine) as session:
        assert session.get(Topic, uuid.UUID(identity)).current_id != old.id
    # In the opposite order, an already committed edit makes the old analysis stale.
    import pytest
    from fastapi import HTTPException

    with Session(engine) as session:
        another = TopicJob(
            id=uuid.uuid4(),
            user_id=owner,
            topic_id=uuid.UUID(identity),
            expected_version=old.id,
            input_text="late old analysis",
            config_version=uuid.UUID(config["version"]),
            destination=config["service_url"],
            model_id=config["model_id"],
            stage="inspect",
            candidate=interpretation(),
            queue_job_id=123457,
            status="running",
        )
        session.add(another)
        session.commit()
        another_id = another.id
    with pytest.raises(HTTPException) as failure:
        topic_worker.accept(
            another_id, json.dumps({"accepted": True, "explanation": "late"}), 123457
        )
    assert failure.value.status_code == 409
    topic_worker.finish(another_id, "invalid_analysis", "stale", 123457)


def test_unsupported_source_never_substitutes_default_case(provider, tmp_path):
    owner, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    identity, _, old = seed_route(owner)
    provider["candidate"] = lambda payload: (
        {
            "accepted": False,
            "explanation": "given source does not support confirmed focus",
        }
        if "candidate" in json.loads(payload["messages"][1]["content"])
        else candidate(payload)
    )
    assert (
        client.post(
            f"/api/v1/topics/{identity}/confirm",
            headers=auth,
            json={"expected_version": str(old.id)},
        ).status_code
        == 200
    )
    started = client.post(
        f"/api/v1/topics/{identity}/start",
        headers=auth,
        json={
            "request_id": str(uuid.uuid4()),
            "expected_version": str(old.id),
            "node_id": str(old.nodes[0].id),
            "expected_config_version": config["version"],
            "disclosure_accepted": True,
        },
    )
    assert started.status_code == 202
    process, _ = start_worker(tmp_path, provider, started.json()["id"])
    try:
        result = wait_run(auth, started.json()["id"]).json()
        assert result["status"] == "failed" and result["case"] is None
        assert result["goal"] == old.nodes[0].text
        assert len(provider["requests"]) == 2
        assert result["code"] == "unsupported_topic"
        assert all(a["total_tokens"] is not None for a in result["attempts"])
        route = client.get(f"/api/v1/topics/{identity}", headers=auth).json()
        assert route["active_id"] == str(old.id) and len(route["versions"]) == 2
    finally:
        stop_worker(process)


def test_partial_usage_stop_retry_and_config_deletion_preserve_result(
    provider, tmp_path
):
    _, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    provider["mode"] = "partial_usage"
    provider["candidate"] = controlled
    body, topic = begin(auth, config)
    process, control = start_worker(
        tmp_path, provider, body["request_id"], observe_usage=True
    )
    try:
        marker = type(control)(str(control) + ".usage_received")
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists()
        url = f"/api/v1/topics/{topic['id']}/jobs/{body['request_id']}"
        response = client.post(url + "/stop", headers=auth)
        assert response.status_code == 200, response.text
        assert response.json()["jobs"][0]["status"] == "stopped"
        provider["release"].set()
        provider["mode"] = "ok"
        assert client.post(url + "/retry", headers=auth).status_code == 200
        completed = wait_topic(auth, topic["id"])
        assert completed["current"] and completed["jobs"][0]["status"] == "completed"
        calls = client.get("/api/v1/model-config/usage", headers=auth).json()["calls"]
        assert len(calls) == 3
        assert next(c for c in calls if c["number"] == 1)["prompt_tokens"] == 11
        deleted = client.request(
            "DELETE",
            "/api/v1/model-config",
            headers=auth,
            params={"expected_version": config["version"]},
        )
        assert deleted.status_code == 204, deleted.text
        assert (
            client.get(f"/api/v1/topics/{topic['id']}", headers=auth).json()["current"]
            == completed["current"]
        )
    finally:
        stop_worker(process)


def test_inspection_temporary_failure_reuses_private_candidate(provider, tmp_path):
    owner, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    identity, _, old = seed_route(owner)
    provider["candidate"] = controlled
    provider["modes"] = ["ok", "temporary", "ok"]
    assert (
        client.post(
            f"/api/v1/topics/{identity}/confirm",
            headers=auth,
            json={"expected_version": str(old.id)},
        ).status_code
        == 200
    )
    started = client.post(
        f"/api/v1/topics/{identity}/start",
        headers=auth,
        json={
            "request_id": str(uuid.uuid4()),
            "expected_version": str(old.id),
            "node_id": str(old.nodes[0].id),
            "expected_config_version": config["version"],
            "disclosure_accepted": True,
        },
    )
    assert started.status_code == 202
    process, _ = start_worker(tmp_path, provider, started.json()["id"])
    try:
        result = wait_run(auth, started.json()["id"]).json()
        assert result["case"], result
        assert len(provider["requests"]) == 3
        assert provider["requests"][1] == provider["requests"][2]
        assert [a["code"] for a in result["attempts"]] == [
            "ok",
            "temporary_service",
            "ok",
        ]
        from app.training.topic_models import TopicCase

        with Session(engine) as session:
            saved = session.get(TopicCase, uuid.UUID(result["id"]))
            assert saved.candidate["title"] == result["case"]["title"]
        assert "HIDDEN_" not in json.dumps(result)
    finally:
        stop_worker(process)


@pytest.mark.parametrize("kind", ["non_engineering", "clarify"])
def test_real_unresolved_analysis_offers_rewrite_without_start(
    provider, tmp_path, kind
):
    _, auth = account()
    config = save(auth, service_url=provider["url"]).json()

    def reply(payload):
        context = json.loads(payload["messages"][1]["content"])["context"]
        return (
            {"accepted": True, "explanation": "已根据输入核对范围或具体缺失信息"}
            if "candidate" in context
            else {
                "kind": kind,
                "message": "请说明想判断的工程情境；这里不处理其他主题",
                "goals": [],
                "recommended_index": None,
            }
        )

    provider["candidate"] = reply
    body, topic = begin(
        auth,
        config,
        input_text="今天吃什么" if kind == "non_engineering" else "这个问题怎么办",
    )
    process, _ = start_worker(tmp_path, provider, body["request_id"])
    try:
        value = wait_topic(auth, topic["id"])
        assert value["current"]["kind"] == kind and value["current"]["nodes"] == []
        assert value["runs"] == [] and value["completed_node_ids"] == []
        assert len(provider["requests"]) == 2
    finally:
        stop_worker(process)


def test_secret_input_is_not_dispatched_and_goal_edit_does_not_open_prerequisite(
    provider, tmp_path
):
    from tests.test_model_config import FAKE_KEY

    owner, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    body, topic = begin(auth, config, input_text="使用这个凭据 " + FAKE_KEY)
    process, _ = start_worker(tmp_path, provider, body["request_id"])
    try:
        value = wait_topic(auth, topic["id"])
        assert (
            value["jobs"][0]["status"] == "failed" and value["jobs"][0]["attempts"] == 0
        )
        assert provider["requests"] == []
    finally:
        stop_worker(process)
    identity, _, old = seed_route(owner)
    goal = old.nodes[0].model_dump(mode="json", exclude={"id"})
    goal["target"]["difficulty"] = "进阶"
    result = client.post(
        f"/api/v1/topics/{identity}/edit",
        headers=auth,
        json={
            "expected_version": str(old.id),
            "operation": "edit",
            "node_id": str(old.nodes[0].id),
            "goal": goal,
        },
    ).json()
    version = result["current"]
    assert (
        client.post(
            f"/api/v1/topics/{identity}/confirm",
            headers=auth,
            json={"expected_version": version["id"]},
        ).status_code
        == 200
    )
    attempt = client.post(
        f"/api/v1/topics/{identity}/start",
        headers=auth,
        json={
            "request_id": str(uuid.uuid4()),
            "expected_version": version["id"],
            "node_id": version["nodes"][0]["id"],
            "expected_config_version": config["version"],
            "disclosure_accepted": True,
        },
    )
    assert attempt.status_code == 409
    assert client.get(f"/api/v1/topics/{identity}", headers=auth).json()["runs"] == []


def test_reconcile_old_stop_snapshot_cannot_stop_new_retry(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from app.training import topic_worker
    from app.training.topic_models import TopicJob

    _, auth = account()
    config = save(auth).json()
    body, topic = begin(auth, config)
    identity = uuid.UUID(body["request_id"])
    with Session(engine) as session:
        job = session.get(TopicJob, identity)
        job.stop_requested = True
        job.status = "stopping"
        session.add(job)
        session.commit()
    entered, release = Event(), Event()
    original = topic_worker.finish

    def pause(*args, **kwargs):
        if args[0] == identity:
            entered.set()
            assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(topic_worker, "finish", pause)
    url = f"/api/v1/topics/{topic['id']}/jobs/{identity}"
    with ThreadPoolExecutor(1) as pool:
        scan = pool.submit(topic_worker.reconcile_topics)
        assert entered.wait(3)
        try:
            assert client.post(url + "/stop", headers=auth).status_code == 200
            assert client.post(url + "/retry", headers=auth).status_code == 200
        finally:
            release.set()
        scan.result()
    value = client.get(f"/api/v1/topics/{topic['id']}", headers=auth).json()
    try:
        assert value["jobs"][0]["status"] == "queued"
    finally:
        client.post(url + "/stop", headers=auth)


def test_recorded_auth_crash_does_not_dispatch_again(provider, tmp_path):
    provider["candidate"] = controlled
    provider["mode"] = "auth"
    _, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    body, topic = begin(auth, config)
    process, control = start_worker(
        tmp_path, provider, body["request_id"], topic_before_finish=True
    )
    try:
        marker = type(control)(str(control) + ".topic_finishing")
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists()
        before = client.get("/api/v1/model-config/usage", headers=auth).json()["calls"]
        assert len(before) == 1 and before[0]["code"] == "authentication"
        process.kill()
        process.wait(timeout=3)
        time.sleep(0.6)  # satisfy the real queue's stalled heartbeat threshold
        process, _ = start_worker(tmp_path, provider, body["request_id"])
        value = wait_topic(auth, topic["id"])
        assert value["jobs"][0]["status"] == "failed"
        assert len(provider["requests"]) == 1
        assert (
            client.get("/api/v1/model-config/usage", headers=auth).json()["calls"]
            == before
        )
    finally:
        stop_worker(process)
