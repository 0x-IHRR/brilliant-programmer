"""Explicit manual online witness; not part of pytest or automatic CI.

Only anonymous public GitHub reads and a locally controlled TLS model are used.
Run from backend cwd after migrating the isolated test database.
"""

import json
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

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
from tests.test_project_public_training import public_material, respond
from tests.test_submissions import wait_submission
from tests.test_topics import wait_topic
from tests.test_training import provider, stop_worker, wait_run

with tempfile.TemporaryDirectory(prefix="bp23-public-") as directory:
    root = Path(directory)
    fixture = provider.__wrapped__(root)
    supplier = next(fixture)
    _, auth = account()
    config = save(auth, service_url=supplier["url"]).json()

    def reply(payload):
        data = json.loads(payload["messages"][1]["content"])
        if data.get("purpose") == "project_map":
            return {"findings": [], "missing": ["实际源码已读取，模型关系未作人工认证"]}
        return respond(payload)

    supplier["candidate"] = reply

    def grade(context):
        assert (
            context["sources"][0]["version"] == public_material()[0].repository.commit
        )
        result = grading(context)
        result["items"][0]["grounding"][0].update(fact="age", value="60")
        result["items"][0]["reason_claims"][0]["interpreted_fact_value"] = "60"
        return result

    supplier["grading"] = grade
    control = root / "control.json"
    control.write_text(json.dumps({"url": supplier["url"], "cert": supplier["cert"]}))
    log = (root / "worker.log").open("w")
    process = subprocess.Popen(
        [sys.executable, "tests/project_training_public_worker.py", str(control)],
        stdout=log,
        stderr=log,
    )
    log.close()
    try:
        started_at = time.monotonic()
        source = client.post(
            "/api/v1/projects",
            headers=auth,
            json={
                "url": "https://github.com/pallets/itsdangerous/blob/672971d66a2ef9f85151e53283113f33d642dabd/src/itsdangerous/timed.py",
                "expected_config_version": config["version"],
                "disclosure_accepted": True,
            },
        )
        assert source.status_code == 202, source.text
        project_id = source.json()["id"]
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            project = client.get(f"/api/v1/projects/{project_id}", headers=auth).json()
            if project["status"] not in {"queued", "running", "stopping"}:
                break
            time.sleep(0.1)
        assert project["snapshot"] and project["project_map"], project
        assert any(
            f["subject"] == "src/itsdangerous/timed.py"
            for f in project["project_map"]["confirmed"]
        )
        topic_id = str(uuid.uuid4())
        requested = client.post(
            "/api/v1/project-training/analyze",
            headers=auth,
            json={
                "request_id": str(uuid.uuid4()),
                "topic_id": topic_id,
                "project_run_id": project_id,
                "expected_config_version": config["version"],
                "disclosure_accepted": True,
            },
        )
        assert requested.status_code == 202, requested.text
        topic = wait_topic(auth, topic_id)
        assert topic["jobs"][0]["status"] == "completed", topic
        version = topic["versions"][0]
        base = f"/api/v1/topics/{topic_id}"
        assert (
            client.post(
                base + "/confirm",
                headers=auth,
                json={"expected_version": version["id"]},
            ).status_code
            == 200
        )
        result = client.post(
            base + "/start",
            headers=auth,
            json={
                "request_id": str(uuid.uuid4()),
                "expected_version": version["id"],
                "node_id": version["nodes"][0]["id"],
                "expected_config_version": config["version"],
                "disclosure_accepted": True,
            },
        )
        assert result.status_code == 202, result.text
        run = wait_run(auth, result.json()["id"]).json()
        assert run["status"] == "completed", run
        submitted = client.post(
            f"/api/v1/training/tasks/{run['id']}/submissions",
            headers=auth,
            json={
                "request_id": str(uuid.uuid4()),
                "answers": [
                    {
                        "judgment_id": "j1",
                        "value": 0,
                        "reason": "源码严格大于max_age才过期，60等于60应返回；61应断言SignatureExpired。",
                    }
                ],
                "expected_config_version": config["version"],
                "disclosure_accepted": True,
            },
        )
        assert submitted.status_code == 202, submitted.text
        assert wait_submission(auth, run["id"])["awarded_points"] == 10
        start_evaluation(auth, run["id"], config)
        evaluation = wait_evaluation(auth, run["id"])
        assert evaluation["status"] == "completed", evaluation
        restored = client.get(
            f"/api/v1/project-training/{topic_id}", headers=auth
        ).json()
        assert restored["topic"]["completed_node_ids"] == [version["nodes"][0]["id"]]
        evidence = {
            "project_id": project_id,
            "topic_id": topic_id,
            "training_id": run["id"],
            "commit": project["snapshot"]["repository"]["commit"],
            "github_requests": project["snapshot"]["requests"],
            "github_bytes": project["snapshot"]["bytes"],
            "seconds": round(time.monotonic() - started_at, 2),
            "model_calls": len(supplier["requests"]),
            "model": "controlled TLS only",
            "evaluation": evaluation["status"],
        }
        out = Path("/tmp/bp-issue-23-artifacts")
        out.mkdir(exist_ok=True)
        (out / "online-entry.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2)
        )
        sys.stdout.write(json.dumps(evidence, ensure_ascii=False) + "\n")
    finally:
        stop_worker(process)
        try:
            next(fixture)
        except StopIteration:
            pass
