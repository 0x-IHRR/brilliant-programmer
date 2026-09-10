"""Controlled upstream failure preserves historical verified acquisition facts."""

import json
import time
from pathlib import Path

import pytest

from tests.test_accounts import client
from tests.test_project import provider as provider
from tests.test_project import start_project, start_worker, wait_run
from tests.test_training import stop_worker, write_control


@pytest.mark.parametrize("status", [404, 403])
def test_unavailable_upstream_keeps_complete_old_snapshot(tmp_path, provider, status):
    auth, old_id = start_project(provider)
    worker, control = start_worker(tmp_path, provider, old_id, before_record="ok")
    try:
        old = wait_run(auth, old_id)
        assert old["status"] == "completed", old
        deadline = time.monotonic() + 15
        while not Path(str(control) + ".recording").exists():
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert old["attempts"] == [
            {
                "number": 1,
                "code": "unknown",
                "prompt_tokens": 11,
                "completion_tokens": 9,
                "total_tokens": 20,
            }
        ]
        options = json.loads(control.read_text())
        options["before_record"] = None
        write_control(control, options)
        while True:
            settled = client.get(f"/api/v1/projects/{old_id}", headers=auth).json()
            if settled["attempts"][0]["code"] == "ok":
                break
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert settled == {**old, "attempts": [{**old["attempts"][0], "code": "ok"}]}
        # Freeze the complete old result only after the separately committed
        # attempt outcome. The test above still proves completed+unknown exists.
        old = settled
        requests = len(provider["requests"])
        provider["github_status"] = status
        _, new_id = start_project(provider, auth)
        failed = wait_run(auth, new_id)
        assert failed["status"] == "failed", failed
        assert failed["snapshot"] is None
        assert failed["reused_from_id"] is None
        assert len(provider["requests"]) == requests
        preserved = client.get(f"/api/v1/projects/{old_id}", headers=auth).json()
        assert preserved["snapshot"] == old["snapshot"]
        assert preserved["project_map"] == old["project_map"]
        assert preserved["attempts"] == old["attempts"]
        history = client.get("/api/v1/projects", headers=auth).json()
        assert {row["id"] for row in history} >= {old_id, new_id}
    finally:
        stop_worker(worker)
