"""Serial actual API/DB/worker browser recovery with synthetic content only."""

import os
import subprocess
import tempfile
from pathlib import Path

from tests.test_accounts import client
from tests.test_training import provider, start_run, start_worker, stop_worker, wait_run

with tempfile.TemporaryDirectory(prefix="draft-browser-") as directory:
    path = Path(directory)
    fixture = provider.__wrapped__(path)
    supplier = next(fixture)
    supplier["all_kinds"] = True
    process = None
    try:
        _, auth, identity = start_run(supplier)
        process, _ = start_worker(path, supplier, identity)
        assert wait_run(auth, identity).json()["status"] == "completed"
        config = client.get("/api/v1/model-config", headers=auth).json()
        second = client.post(
            "/api/v1/training/random",
            headers=auth,
            json={
                "disclosure_accepted": True,
                "expected_config_version": config["version"],
                "previous_run_id": identity,
            },
        )
        assert second.status_code == 202
        second_id = second.json()["id"]
        assert wait_run(auth, second_id).json()["status"] == "completed"
        subprocess.run(
            ["bun", "run", "--cwd", "../frontend", "test", "draft.spec.ts"],
            env={
                **os.environ,
                "DRAFT_BROWSER_TOKEN": auth["Authorization"].removeprefix("Bearer "),
                "DRAFT_FIRST_RUN": identity,
                "DRAFT_SECOND_RUN": second_id,
            },
            check=True,
        )
        assert len(supplier["requests"]) == 2
        for run_id in [identity, second_id]:
            state = client.get(
                f"/api/v1/training/tasks/{run_id}/submissions", headers=auth
            ).json()
            assert not state["submissions"] and state["awarded_points"] == 0
    finally:
        if process:
            stop_worker(process)
        try:
            next(fixture)
        except StopIteration:
            pass
