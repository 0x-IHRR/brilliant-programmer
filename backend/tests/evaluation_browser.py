"""Actual browser evaluation, serial with the other controlled worker suites."""

import os
import subprocess
import tempfile
import uuid
from pathlib import Path

from tests.test_accounts import client
from tests.test_evaluations import grading
from tests.test_submissions import wait_submission
from tests.test_training import provider, start_run, start_worker, stop_worker, wait_run

with tempfile.TemporaryDirectory(prefix="evaluation-browser-") as directory:
    path = Path(directory)
    fixture = provider.__wrapped__(path)
    supplier = next(fixture)
    supplier["grading"] = lambda context: grading(
        context, "unclear" if not context["inputs"]["clarification"] else "pass"
    )
    process = None
    try:
        _, auth, identity = start_run(supplier)
        process, _ = start_worker(path, supplier, identity)
        assert wait_run(auth, identity).json()["status"] == "completed"
        config = client.get("/api/v1/model-config", headers=auth).json()
        response = client.post(
            f"/api/v1/training/tasks/{identity}/submissions",
            headers=auth,
            json={
                "request_id": str(uuid.uuid4()),
                "expected_config_version": config["version"],
                "disclosure_accepted": True,
                "evaluate_after_submit": True,
                "answers": [
                    {
                        "judgment_id": "j1",
                        "value": 0,
                        "reason": "尚不能确认，我想核对原答的意思。",
                    }
                ],
            },
        )
        assert response.status_code == 202
        assert wait_submission(auth, identity)["awarded_points"] == 10
        subprocess.run(
            ["bun", "run", "--cwd", "../frontend", "test", "evaluation.spec.ts"],
            env={
                **os.environ,
                "EVALUATION_BROWSER_TOKEN": auth["Authorization"].removeprefix(
                    "Bearer "
                ),
            },
            check=True,
        )
        assert len(supplier["requests"]) == 4
    finally:
        if process:
            stop_worker(process)
        try:
            next(fixture)
        except StopIteration:
            pass
