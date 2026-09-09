"""Synthetic real target-start/worker/browser; no external paid provider."""

import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path

from app.capabilities.catalog import CATALOG
from tests.capability_scenarios import comparisons, scenario
from tests.test_accounts import client
from tests.test_evaluations import grading
from tests.test_guided import frozen
from tests.test_model_config import account, save
from tests.test_training import provider, start_worker, stop_worker
from tests.test_unlock_api import BASE

with tempfile.TemporaryDirectory(prefix="unlock-browser-") as directory:
    path = Path(directory)
    fixture = provider.__wrapped__(path)
    supplier = next(fixture)
    process = None
    try:
        _, auth = account()
        config = save(auth, service_url=supplier["url"]).json()
        index = [0]

        def response(payload):
            context = json.loads(payload["messages"][1]["content"])
            if "new" in context:
                return comparisons(context)
            case = scenario(frozen.__wrapped__()[0], index[0]).model_dump()
            index[0] += 1
            case["target"] = context["target"]
            case["evidence"][0]["citations"] = [
                {
                    "source_id": context["sources"][0]["id"],
                    "quote": context["sources"][0]["text"][:100],
                }
            ]
            return case

        def grade(context):
            result = grading(context)
            value = context["task"]["evidence"][0]["facts"]["ack"]
            for item in result["items"]:
                item["grounding"][0].update(fact="ack", value=value)
                item["reason_claims"][0]["interpreted_fact_value"] = value
            return result

        supplier["candidate"] = response
        supplier["grading"] = grade
        # Start an idle real worker using a known owned queued task, then stop it
        # before worker startup; it supplies only identity to the test adapter.
        seeded = client.post(
            "/api/v1/capabilities/start",
            headers=auth,
            json={
                "request_id": str(uuid.uuid4()),
                "target": BASE.model_dump(),
                "catalog_version": CATALOG.version,
                "mode": "independent",
                "disclosure_accepted": True,
                "expected_config_version": config["version"],
            },
        )
        assert seeded.status_code == 202
        identity = seeded.json()["id"]
        assert (
            client.post(
                f"/api/v1/training/tasks/{identity}/stop", headers=auth
            ).status_code
            == 200
        )
        process, _ = start_worker(path, supplier, identity)
        subprocess.run(
            ["bun", "run", "--cwd", "../frontend", "test", "unlocks.spec.ts"],
            env={
                **os.environ,
                "UNLOCK_BROWSER_TOKEN": auth["Authorization"].removeprefix("Bearer "),
            },
            check=True,
        )
        assert len(supplier["requests"]) == 9
    finally:
        if process:
            stop_worker(process)
        try:
            next(fixture)
        except StopIteration:
            pass
