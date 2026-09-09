"""Controlled TLS exercises provenance, not real-model JD interpretation quality."""

import json
import time
import uuid

import pytest

from tests.test_accounts import client
from tests.test_jd_rules import sample
from tests.test_model_config import account, save
from tests.test_topics import controlled
from tests.test_training import provider as provider
from tests.test_training import start_worker, stop_worker, wait_run


def wait_jd(auth, identity):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/jds/{identity}", headers=auth)
        assert response.status_code == 200, response.text
        state = response.json()
        if all(
            j["status"] in {"completed", "failed", "stopped"}
            for j in state["topic"]["jobs"]
        ):
            return state
        time.sleep(0.05)
    raise AssertionError(state)


def test_jd_real_analysis_selected_provenance_and_generation(provider, tmp_path):
    _, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    document, analysis = sample()

    def response(payload):
        content = json.loads(payload["messages"][1]["content"])
        if "jd_text" in content.get("context", {}):
            if "candidate" in content["context"]:
                return {
                    "accepted": True,
                    "explanation": "原文精确要求引用与推断标记匹配受控样本",
                }
            return analysis.model_dump(mode="json")
        return controlled(payload)

    provider["candidate"] = response
    body = {
        "request_id": str(uuid.uuid4()),
        "topic_id": str(uuid.uuid4()),
        "input_text": document.text,
        "expected_config_version": config["version"],
        "disclosure_accepted": True,
    }
    result = client.post("/api/v1/jds/analyze", headers=auth, json=body)
    assert result.status_code == 202, result.text
    process, _ = start_worker(tmp_path, provider, body["request_id"])
    try:
        state = wait_jd(auth, body["topic_id"])
        assert state["topic"]["jobs"][0]["status"] == "completed", state
        assert state["current"] is None and state["topic"]["runs"] == []
        assert state["documents"][0]["document"]["text"] == document.text
        assert len(provider["requests"]) == 2
        selected = client.post(
            f"/api/v1/jds/{body['topic_id']}/select",
            headers=auth,
            json={"document_id": body["request_id"], "role_index": 0},
        )
        assert selected.status_code == 200, selected.text
        state = selected.json()
        current = state["current"]["route"]
        assert state["evidence"][0]["status"] == "unverified"
        assert state["semantic_reliability"] == "unverified"
        url = f"/api/v1/topics/{body['topic_id']}"
        start = {
            "request_id": str(uuid.uuid4()),
            "expected_version": current["id"],
            "node_id": current["nodes"][0]["id"],
            "expected_config_version": config["version"],
            "disclosure_accepted": True,
        }
        assert client.post(url + "/start", headers=auth, json=start).status_code == 409
        assert (
            client.post(
                url + "/confirm", headers=auth, json={"expected_version": current["id"]}
            ).status_code
            == 200
        )
        result = client.post(url + "/start", headers=auth, json=start)
        assert result.status_code == 202, result.text
        generated = wait_run(auth, result.json()["id"]).json()
        assert generated["case"], generated
        assert len(provider["requests"]) == 4
        sent = json.loads(provider["requests"][2]["messages"][1]["content"])
        assert sent["confirmed_topic"]["requirement_quote"] == "处理请求重试"
        assert sent["confirmed_topic"]["basis"] == "inferred"
        assert sent["confirmed_topic"]["simulation_label"] == "教学模拟"
        assert document.text not in json.dumps(sent, ensure_ascii=False)
        assert "联系邮箱" not in json.dumps(sent, ensure_ascii=False)
        assert (
            client.post(url + "/start", headers=auth, json=start).json()["id"]
            == generated["id"]
        )
    finally:
        stop_worker(process)


def seeded(auth, config, count=3, kind="roles", mixed=False):
    from sqlmodel import Session, select

    from app.core.db import engine
    from app.models import User
    from app.training.jd_models import JDAnalysis, JDDocument, JDTopic
    from app.training.jd_rules import Analysis, Quote
    from app.training.topic_models import Topic, TopicJob

    doc, analysis = sample(count)
    if kind != "roles":
        analysis = Analysis(kind=kind, message="请补充具体岗位职责或技术背景")
    if mixed:
        second = analysis.roles[0].model_copy(
            update={
                "name": "前端岗位",
                "quote": Quote(start=15, end=19, text="前端岗位"),
            }
        )
        analysis = analysis.model_copy(update={"roles": (*analysis.roles, second)})
    me = client.get("/api/v1/users/me", headers=auth).json()
    with Session(engine) as s:
        user = s.exec(select(User).where(User.id == uuid.UUID(me["id"]))).one()
        topic = Topic(user_id=user.id)
        s.add(topic)
        s.flush()
        s.add(JDTopic(topic_id=topic.id))
        job = TopicJob(
            id=doc.id,
            topic_id=topic.id,
            user_id=user.id,
            input_text=doc.text,
            config_version=uuid.UUID(config["version"]),
            destination=config["service_url"],
            model_id=config["model_id"],
            status="completed",
            code="ok",
            stage="inspect",
        )
        s.add(job)
        s.flush()
        s.add(JDDocument(id=doc.id, topic_id=topic.id, text=doc.text))
        s.flush()
        s.add(JDAnalysis(document_id=doc.id, snapshot=analysis.model_dump(mode="json")))
        s.commit()
        return str(topic.id), str(doc.id)


def test_jd_roles_cas_reorder_edit_preserve_claim_and_owner():
    _, auth = account()
    config = save(auth).json()
    topic, doc = seeded(auth, config, mixed=True)
    url = f"/api/v1/jds/{topic}"
    state = client.get(url, headers=auth).json()
    assert state["current"] is None
    assert len(state["documents"][0]["analysis"]["roles"]) == 2
    assert all(
        v["status"] == "unverified"
        for values in state["documents"][0]["evidence"]
        for v in values
    )
    selected = client.post(
        url + "/select", headers=auth, json={"document_id": doc, "role_index": 1}
    )
    assert selected.status_code == 200, selected.text
    first = selected.json()["current"]
    assert first["role_name"] == "前端岗位"
    common = f"/api/v1/topics/{topic}"
    nodes = first["route"]["nodes"]
    reordered = client.post(
        common + "/edit",
        headers=auth,
        json={
            "expected_version": first["route"]["id"],
            "operation": "reorder",
            "order": [n["id"] for n in reversed(nodes)],
        },
    )
    assert reordered.status_code == 200, reordered.text
    second = client.get(url, headers=auth).json()["current"]
    assert [n["id"] for n in second["route"]["nodes"]] == [
        n["id"] for n in reversed(nodes)
    ]
    goal = {k: nodes[-1][k] for k in ("text", "focus", "target")}
    goal["focus"] = "先查服务端执行记录，再决定是否重复提交"
    body = {
        "expected_version": second["route"]["id"],
        "operation": "edit",
        "node_id": nodes[-1]["id"],
        "goal": goal,
    }
    assert client.post(common + "/edit", headers=auth, json=body).status_code == 200
    assert client.post(common + "/edit", headers=auth, json=body).status_code == 409
    third = client.get(url, headers=auth).json()["current"]
    assert third["route"]["nodes"][0]["id"] != nodes[-1]["id"]
    assert third["route"]["nodes"][0]["focus"] == goal["focus"]
    assert third["mappings"][0]["requirement"] == second["mappings"][0]["requirement"]
    assert third["document"] == first["document"]
    assert client.get(url, headers=auth).json()["topic"]["active_id"] is None
    _, other = account()
    assert client.get(url, headers=other).status_code == 404
    assert (
        client.post(
            url + "/select", headers=other, json={"document_id": doc, "role_index": 0}
        ).status_code
        == 404
    )
    assert not any(
        v["id"] == topic for v in client.get("/api/v1/topics", headers=auth).json()
    )


def test_jd_unresolved_and_configuration_removed_keep_original():
    _, auth = account()
    config = save(auth).json()
    topic, doc = seeded(auth, config, kind="no_requirements")
    url = f"/api/v1/jds/{topic}"
    assert (
        client.post(
            url + "/select", headers=auth, json={"document_id": doc, "role_index": 0}
        ).status_code
        == 422
    )
    before = client.get(url, headers=auth).json()
    assert (
        before["current"] is None
        and before["documents"][0]["analysis"]["kind"] == "no_requirements"
    )
    deleted = client.delete(
        "/api/v1/model-config",
        headers=auth,
        params={"expected_version": config["version"]},
    )
    assert deleted.status_code == 204, deleted.text
    assert client.get(url, headers=auth).json() == before


@pytest.mark.parametrize(
    "mode",
    [
        "no_requirements",
        "clarify",
        "bad_quote",
        "rejected",
        "secret",
        "multi",
        "unknown_background",
    ],
)
def test_jd_actual_analysis_refuses_unusable_or_unsafe_content(
    provider, tmp_path, mode
):
    from tests.test_model_config import FAKE_KEY

    _, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    document, analysis = sample()
    payload = analysis.model_dump(mode="json")
    if mode in {"no_requirements", "clarify"}:
        payload = {"kind": mode, "message": "请补充岗位要求或明确背景", "roles": []}
    if mode == "multi":
        payload["roles"].append(
            {
                **payload["roles"][0],
                "name": "前端岗位",
                "quote": {"start": 15, "end": 19, "text": "前端岗位"},
                "requirements": [
                    {
                        "quote": {"start": 15, "end": 19, "text": "前端岗位"},
                        "basis": "inferred",
                        "explanation": "前端岗位没有更具体背景；先补充，不默认网络能力",
                        "goal": None,
                    }
                ],
            }
        )
    if mode == "unknown_background":
        payload["roles"][0]["requirements"][0]["goal"] = None
    if mode == "bad_quote":
        payload["roles"][0]["requirements"][0]["quote"]["text"] = "并非原文内容"

    def respond(request):
        context = json.loads(request["messages"][1]["content"])["context"]
        if "candidate" in context:
            return {
                "accepted": mode != "rejected",
                "explanation": "受控核对实际引用与原文，无法确认则拒绝",
            }
        return payload

    provider["candidate"] = respond
    body = {
        "request_id": str(uuid.uuid4()),
        "topic_id": str(uuid.uuid4()),
        "input_text": document.text + (FAKE_KEY if mode == "secret" else ""),
        "expected_config_version": config["version"],
        "disclosure_accepted": True,
    }
    result = client.post("/api/v1/jds/analyze", headers=auth, json=body)
    assert result.status_code == 202, result.text
    process, _ = start_worker(tmp_path, provider, body["request_id"])
    try:
        state = wait_jd(auth, body["topic_id"])
        assert state["current"] is None and state["topic"]["runs"] == []
        job = state["topic"]["jobs"][0]
        assert job["status"] == (
            "completed"
            if mode in {"no_requirements", "clarify", "multi", "unknown_background"}
            else "failed"
        )
        assert len(provider["requests"]) == (
            0 if mode == "secret" else 1 if mode == "bad_quote" else 2
        )
        assert state["documents"][0]["document"]["text"] == body["input_text"]
        assert job["attempts"] == len(provider["requests"])
    finally:
        stop_worker(process)


def test_jd_stop_resume_preserves_received_usage_and_same_document(provider, tmp_path):
    _, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    document, analysis = sample()
    provider["mode"] = "partial_usage"

    def respond(payload):
        data = json.loads(payload["messages"][1]["content"])["context"]
        return (
            {"accepted": True, "explanation": "受控精确引用核对"}
            if "candidate" in data
            else analysis.model_dump(mode="json")
        )

    provider["candidate"] = respond
    body = {
        "request_id": str(uuid.uuid4()),
        "topic_id": str(uuid.uuid4()),
        "input_text": document.text,
        "expected_config_version": config["version"],
        "disclosure_accepted": True,
    }
    response = client.post("/api/v1/jds/analyze", headers=auth, json=body)
    assert response.status_code == 202, response.text
    process, control = start_worker(
        tmp_path, provider, body["request_id"], observe_usage=True
    )
    try:
        marker = type(control)(str(control) + ".usage_received")
        deadline = time.monotonic() + 8
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists(), "consumer has not observed partial usage"
        url = f"/api/v1/topics/{body['topic_id']}/jobs/{body['request_id']}"
        stopped = client.post(url + "/stop", headers=auth)
        assert stopped.status_code == 200, stopped.text
        assert stopped.json()["jobs"][0]["status"] == "stopped"
        pending = client.get(f"/api/v1/jds/{body['topic_id']}", headers=auth).json()
        assert (
            pending["documents"][0]["analysis"] is None and pending["current"] is None
        )
        provider["release"].set()
        provider["mode"] = "ok"
        retry = client.post(url + "/retry", headers=auth)
        assert retry.status_code == 200, retry.text
        complete = wait_jd(auth, body["topic_id"])
        assert complete["topic"]["jobs"][0]["status"] == "completed", complete
        assert (
            len(complete["documents"]) == 1
            and complete["documents"][0]["document"]["id"] == body["request_id"]
        )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            calls = client.get("/api/v1/model-config/usage", headers=auth).json()[
                "calls"
            ]
            if len(calls) == 3 and all(
                c["code"] == "ok" for c in calls if c["number"] > 1
            ):
                break
            time.sleep(0.01)
        assert len(calls) == 3
        assert next(c for c in calls if c["number"] == 1)["prompt_tokens"] == 11
        assert all(c["code"] == "ok" for c in calls if c["number"] > 1)
        replay = client.post("/api/v1/jds/analyze", headers=auth, json=body)
        assert replay.status_code == 202
        assert len(replay.json()["documents"]) == 1
        assert len(provider["requests"]) == 3
    finally:
        stop_worker(process)


def test_jd_missing_prerequisites_refuses_without_changing_confirmed_target():
    from app.capabilities.catalog import CATALOG, EvidenceKey
    from app.training.topic_rules import Goal

    _, auth = account()
    config = save(auth).json()
    topic, doc = seeded(auth, config, count=1)
    selected = client.post(
        f"/api/v1/jds/{topic}/select",
        headers=auth,
        json={"document_id": doc, "role_index": 0},
    ).json()
    first = selected["current"]["route"]
    target = next(
        EvidenceKey(
            capability_id=capability.id,
            background_id=capability.background_id,
            difficulty=level.difficulty,
        )
        for domain in CATALOG.domains
        for capability in domain.capabilities
        for level in capability.levels
        if level.required
    )
    goal = Goal(target=target, text="明确改为此进阶判断", focus="保留真实前置要求")
    base = f"/api/v1/topics/{topic}"
    changed = client.post(
        base + "/edit",
        headers=auth,
        json={
            "expected_version": first["id"],
            "operation": "edit",
            "node_id": first["nodes"][0]["id"],
            "goal": goal.model_dump(mode="json"),
        },
    )
    assert changed.status_code == 200, changed.text
    current = changed.json()["current"]
    confirmed = client.post(
        base + "/confirm", headers=auth, json={"expected_version": current["id"]}
    )
    assert confirmed.status_code == 200
    started = client.post(
        base + "/start",
        headers=auth,
        json={
            "request_id": str(uuid.uuid4()),
            "expected_version": current["id"],
            "node_id": current["nodes"][0]["id"],
            "expected_config_version": config["version"],
            "disclosure_accepted": True,
        },
    )
    assert started.status_code == 409, started.text
    assert started.json()["detail"]["access"]["target"] == target.model_dump()
    after = client.get(f"/api/v1/jds/{topic}", headers=auth).json()
    assert after["current"]["route"] == current and after["topic"]["runs"] == []


def test_jd_authentication_verification_and_validation_do_not_echo_input():
    from tests.test_model_config import FAKE_KEY

    unauthenticated = client.get("/api/v1/jds")
    assert unauthenticated.status_code == 401
    _, unverified = account(verified=False)
    forbidden = client.get("/api/v1/jds", headers=unverified)
    assert forbidden.status_code == 403
    _, auth = account()
    invalid = client.post(
        "/api/v1/jds/analyze",
        headers=auth,
        json={"request_id": FAKE_KEY, "input_text": FAKE_KEY},
    )
    assert invalid.status_code == 422
    assert FAKE_KEY not in invalid.text
