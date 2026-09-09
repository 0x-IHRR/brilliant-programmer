"""Actual review UI with real HTTP, database and controlled TLS queue worker."""

import os
import subprocess
import tempfile
import uuid
from pathlib import Path

from tests.test_accounts import client
from tests.test_evaluations import endpoint, grading, wait
from tests.test_submissions import wait_submission
from tests.test_training import provider, start_run, start_worker, stop_worker, wait_run

with tempfile.TemporaryDirectory(prefix="review-browser-") as directory:
    path = Path(directory)
    fixture = provider.__wrapped__(path)
    supplier = next(fixture)
    supplier["grading"] = lambda context: grading(context, "unclear")
    supplier["review"] = lambda context: {
        "decision": "corrected",
        "explanation": "复核原答及原来源后确认：原答的表达有据，原评分未确认其语义。",
        "grading": grading(context),
    }
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
                        "reason": "确认可能丢失，因此不能断言请求没有执行。",
                    }
                ],
            },
        )
        assert response.status_code == 202
        assert wait_submission(auth, identity)["awarded_points"] == 10
        assert wait(auth, identity)["status"] == "needs_clarification"
        assert (
            client.post(
                endpoint(identity) + "/clarification",
                headers=auth,
                json={"answers": None},
            ).status_code
            == 202
        )
        subprocess.run(
            ["bun", "run", "--cwd", "../frontend", "test", "review.spec.ts"],
            env={
                **os.environ,
                "REVIEW_BROWSER_TOKEN": auth["Authorization"].removeprefix("Bearer "),
                "REVIEW_BROWSER_RUN": identity,
            },
            check=True,
        )
        current = client.get(
            f"/api/v1/training/tasks/{identity}/review", headers=auth
        ).json()
        assert current["decision"] == "corrected" and len(current["attempts"]) == 1
        assert wait_submission(auth, identity)["total_points"] == 10
        assert len(supplier["requests"]) == 4
    finally:
        if process:
            stop_worker(process)
        try:
            next(fixture)
        except StopIteration:
            pass
