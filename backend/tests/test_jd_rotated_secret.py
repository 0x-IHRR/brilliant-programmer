"""A previously safe JD quote can contain the newly selected synthetic Key."""

import json
import uuid

from tests.test_accounts import client
from tests.test_jd_rules import sample
from tests.test_jds import wait_jd
from tests.test_model_config import account, save
from tests.test_topics import controlled
from tests.test_training import provider as provider
from tests.test_training import start_worker, stop_worker, wait_run


def test_rotated_key_in_frozen_quote_is_blocked_before_first_generation(
    provider, tmp_path
):
    _, auth = account()
    old = save(auth, service_url=provider["url"]).json()
    document, analysis = sample()
    replacement = "abcdefghijklmnop"
    quote = "处理请求重试 " + replacement
    original = "后端工程师：" + quote + "。"
    payload = analysis.model_dump(mode="json")
    payload["roles"][0]["requirements"][0]["quote"] = {
        "start": 6,
        "end": 6 + len(quote),
        "text": quote,
    }

    def respond(request):
        body = json.loads(request["messages"][1]["content"])
        if "jd_text" in body.get("context", {}):
            return (
                {"accepted": True, "explanation": "精确原文引用已核对"}
                if "candidate" in body["context"]
                else payload
            )
        return controlled(request)

    provider["candidate"] = respond
    request = {
        "request_id": str(uuid.uuid4()),
        "topic_id": str(uuid.uuid4()),
        "input_text": original,
        "expected_config_version": old["version"],
        "disclosure_accepted": True,
    }
    response = client.post("/api/v1/jds/analyze", headers=auth, json=request)
    assert response.status_code == 202
    process, _ = start_worker(tmp_path, provider, request["request_id"])
    try:
        analyzed = wait_jd(auth, request["topic_id"])
        assert analyzed["topic"]["jobs"][0]["status"] == "completed"
        selected = client.post(
            f"/api/v1/jds/{request['topic_id']}/select",
            headers=auth,
            json={"document_id": request["request_id"], "role_index": 0},
        )
        assert selected.status_code == 200
        version = selected.json()["current"]["route"]
        topic_url = f"/api/v1/topics/{request['topic_id']}"
        confirmed = client.post(
            topic_url + "/confirm",
            headers=auth,
            json={"expected_version": version["id"]},
        )
        assert confirmed.status_code == 200
        changed = save(
            auth,
            service_url=provider["url"],
            expected_version=old["version"],
            api_key=replacement,
        )
        assert changed.status_code == 200
        count_before = len(provider["requests"])
        assert count_before == 2
        started = client.post(
            topic_url + "/start",
            headers=auth,
            json={
                "request_id": str(uuid.uuid4()),
                "expected_version": version["id"],
                "node_id": version["nodes"][0]["id"],
                "expected_config_version": changed.json()["version"],
                "disclosure_accepted": True,
            },
        )
        assert started.status_code == 202
        final = wait_run(auth, started.json()["id"]).json()
        count_after = len(provider["requests"])
        # Never print the payload or synthetic Key in diagnostics.
        assert count_after == count_before, "new generation dispatched forbidden quote"
        assert final["status"] == "failed" and final["code"] == "unsafe_input"
        assert final["attempts"] == [] and final["case"] is None
    finally:
        stop_worker(process)
