import uuid

import pytest

from app.project.analysis import syntax_map
from app.project.schema import Location
from tests.test_accounts import client
from tests.test_model_config import account, save
from tests.test_project_training_api import begin, response_for
from tests.test_project_training_rules import material as material
from tests.test_topics import wait_topic
from tests.test_training import provider as provider
from tests.test_training import start_worker, stop_worker, wait_run


@pytest.mark.parametrize("independent", [False, True])
def test_rotated_key_in_project_source_never_dispatches_or_spends_attempt(
    provider, tmp_path, material, independent
):
    future_key = "abcdefghijklmnopqrstuvwx"
    snapshot, _, goal = material
    old = snapshot.fragments[0]
    content = old.text.rstrip("\n") + " # " + future_key + "\n"
    fragment = old.model_copy(update={"text": content})
    snapshot = snapshot.model_copy(update={"fragments": [fragment]})
    goal = goal.model_copy(
        update={
            "evidence": (
                Location(
                    path=fragment.path, start=1, end=2, quote=content.rstrip("\n")
                ),
            )
        }
    )
    material = snapshot, syntax_map([fragment]), goal
    _, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    provider["candidate"] = response_for(material)
    body = begin(auth, config, material)
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
        start = {
            "request_id": str(uuid.uuid4()),
            "expected_version": version["id"],
            "node_id": version["nodes"][0]["id"],
            "expected_config_version": config["version"],
            "disclosure_accepted": True,
        }
        if independent:
            original = client.post(path + "/start", headers=auth, json=start)
            assert original.status_code == 202
            assert wait_run(auth, original.json()["id"]).json()["status"] == "completed"
        rotated = save(
            auth,
            service_url=provider["url"],
            expected_version=config["version"],
            api_key=future_key,
        )
        assert rotated.status_code == 200
        before = len(provider["requests"])
        if independent:
            started = client.post(
                f"/api/v1/training/tasks/{original.json()['id']}/independent",
                headers=auth,
                json={
                    "request_id": str(uuid.uuid4()),
                    "expected_config_version": rotated.json()["version"],
                    "disclosure_accepted": True,
                },
            )
        else:
            started = client.post(
                path + "/start",
                headers=auth,
                json={**start, "expected_config_version": rotated.json()["version"]},
            )
        assert started.status_code == 202, started.text
        result = wait_run(auth, started.json()["id"]).json()
        assert result["status"] == "failed" and result["code"] == "unsafe_input"
        assert result["attempts"] == [] and result["case"] is None
        assert len(provider["requests"]) == before, (
            "forbidden project source was dispatched"
        )
    finally:
        stop_worker(process)
