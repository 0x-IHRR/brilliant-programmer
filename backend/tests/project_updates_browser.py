"""Real API/UI state isolation with controlled route generation only."""

import os
import subprocess
import tempfile
import uuid
from pathlib import Path

from tests.test_accounts import client
from tests.test_model_config import account, save
from tests.test_project_training_api import response_for
from tests.test_project_training_rules import material
from tests.test_project_updates import confirm, seeded, source
from tests.test_topics import wait_topic
from tests.test_training import provider, start_worker, stop_worker

with tempfile.TemporaryDirectory(prefix="bp24-browser-") as directory:
    root = Path(directory)
    fixture = provider.__wrapped__(root)
    supplier = next(fixture)
    owner, auth = account()
    config = save(auth, service_url=supplier["url"]).json()
    content = material.__wrapped__()
    topic_a, original = seeded(owner, config, content)
    assert confirm(auth, topic_a, original.route.id).status_code == 200
    new_source = source(owner, config, content)
    topic_b = uuid.uuid4()
    body = {
        "request_id": str(uuid.uuid4()),
        "topic_id": str(topic_b),
        "project_run_id": str(new_source),
        "previous_version_id": str(original.route.id),
        "expected_active_version": str(original.route.id),
        "expected_config_version": config["version"],
        "disclosure_accepted": True,
    }
    supplier["candidate"] = response_for(content)
    response = client.post("/api/v1/project-training/analyze", headers=auth, json=body)
    assert response.status_code == 202
    worker, _ = start_worker(root, supplier, body["request_id"])
    try:
        state = wait_topic(auth, str(topic_b))
        assert state["jobs"][0]["status"] == "completed", state
        assert state["current"]["nodes"][0]["id"] == str(original.route.nodes[0].id)
        subprocess.run(
            ["bun", "run", "--cwd", "../frontend", "test", "project-updates.spec.ts"],
            check=True,
            env={
                **os.environ,
                "PROJECT_UPDATES_TOKEN": auth["Authorization"].removeprefix("Bearer "),
                "PROJECT_UPDATES_SOURCE": str(new_source),
                "PROJECT_UPDATES_A": str(topic_a),
                "PROJECT_UPDATES_B": str(topic_b),
            },
        )
        assert len(supplier["requests"]) == 2
    finally:
        stop_worker(worker)
        try:
            next(fixture)
        except StopIteration:
            pass
