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
        switch_auth = login(client.get("/api/v1/users/me", headers=auth).json()["email"])
        _, other_auth = account()
        assert save(other_auth, service_url=supplier["url"]).status_code == 200
        subprocess.run(
            ["bun", "run", "--cwd", "../frontend", "test", "draft.spec.ts", *sys.argv[1:]],
            env={
                **os.environ,
                "DRAFT_BROWSER_TOKEN": auth["Authorization"].removeprefix("Bearer "),
                "DRAFT_FIRST_RUN": identity,
                "DRAFT_SWITCH_TOKEN": switch_auth["Authorization"].removeprefix("Bearer "),
                "DRAFT_OTHER_TOKEN": other_auth["Authorization"].removeprefix("Bearer "),
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
