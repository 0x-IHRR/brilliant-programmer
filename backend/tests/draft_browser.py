"""Serial actual API/DB/worker browser recovery with synthetic content only."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from tests.test_accounts import client, login
from tests.test_model_config import account, save
from tests.test_training import provider, start_run, start_worker, stop_worker, wait_run

with tempfile.TemporaryDirectory(prefix="draft-browser-") as directory:
    path = Path(directory)
    fixture = provider.__wrapped__(path)
    supplier = next(fixture)
    supplier["all_kinds"] = True
    process = None
    submission_guard = False
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
        switch_auth = login(
            client.get("/api/v1/users/me", headers=auth).json()["email"]
        )
        _, other_auth = account()
        assert save(other_auth, service_url=supplier["url"]).status_code == 200
        submission_guard = os.environ.get("DRAFT_TEST_FILE") == "draft-submit-guard.spec.ts"
        if submission_guard:
            stop_worker(process)
            process = None
        subprocess.run(
            [
                "bun",
                "run",
                "--cwd",
                "../frontend",
                "test",
                os.environ.get("DRAFT_TEST_FILE", "draft.spec.ts"),
                *sys.argv[1:],
            ],
            env={
                **os.environ,
                "DRAFT_BROWSER_TOKEN": auth["Authorization"].removeprefix("Bearer "),
                "DRAFT_FIRST_RUN": identity,
                "DRAFT_SWITCH_TOKEN": switch_auth["Authorization"].removeprefix(
                    "Bearer "
                ),
                "DRAFT_OTHER_TOKEN": other_auth["Authorization"].removeprefix(
                    "Bearer "
                ),
                "DRAFT_SECOND_RUN": second_id,
            },
            check=True,
        )
        assert len(supplier["requests"]) == 2
        for run_id in [identity, second_id]:
            state = client.get(
                f"/api/v1/training/tasks/{run_id}/submissions", headers=auth
            ).json()
            assert state["awarded_points"] == 0
            if submission_guard and run_id == identity:
                assert len(state["submissions"]) == 1
                assert all(a["reason"] == "选择的新版本 B" for a in state["submissions"][0]["answers"])
            else:
                assert not state["submissions"]
    finally:
        if submission_guard:
            # Keep this real queued submit from leaking into the next browser worker.
            records = client.get(
                f"/api/v1/training/tasks/{identity}/submissions", headers=auth
            ).json()
            for item in records["submissions"]:
                response = client.post(
                    f"/api/v1/training/tasks/{identity}/submissions/{item['id']}/stop",
                    headers=auth,
                )
                assert response.status_code == 200
        if process:
            stop_worker(process)
        try:
            next(fixture)
        except StopIteration:
            pass
