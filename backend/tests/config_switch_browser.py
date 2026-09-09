"""Serial real-worker cancellation through the configuration UI."""

import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from app.model_config.revocation import request_revocation
from tests.test_accounts import client
from tests.test_concepts import coach, request
from tests.test_model_config import account, save
from tests.test_training import provider, start_run, start_worker, stop_worker, wait_run

with tempfile.TemporaryDirectory(prefix="config-switch-browser-") as directory:
    path = Path(directory)
    fixture = provider.__wrapped__(path)
    supplier = next(fixture)
    supplier["coach"] = coach
    process = None
    try:
        _, auth, identity = start_run(supplier)
        process, control = start_worker(path, supplier, identity, observe_usage=True)
        assert wait_run(auth, identity).json()["status"] == "completed"
        config = client.get("/api/v1/model-config", headers=auth).json()
        supplier["mode"] = "partial_usage"
        _, _ = request(auth, identity, config)
        deadline = time.monotonic() + 8
        while not Path(str(control) + ".usage_received").exists():
            assert time.monotonic() < deadline
            time.sleep(0.02)
        recovery_owner, recovery_auth = account()
        recovery = save(recovery_auth, service_url=supplier["url"]).json()
        request_revocation(recovery_owner, uuid.UUID(recovery["version"]))
        subprocess.run(
            ["bun", "run", "--cwd", "../frontend", "test", "config-switch.spec.ts"],
            env={
                **os.environ,
                "CONFIG_SWITCH_TOKEN": auth["Authorization"].removeprefix("Bearer "),
                "CONFIG_SWITCH_RUN": identity,
                "CONFIG_RECOVERY_TOKEN": recovery_auth["Authorization"].removeprefix(
                    "Bearer "
                ),
            },
            check=True,
        )
        assert len(supplier["requests"]) == 2
        assert (
            client.get(f"/api/v1/training/tasks/{identity}/help", headers=auth).json()[
                0
            ]["status"]
            == "stopped"
        )
    finally:
        if process:
            stop_worker(process)
        try:
            next(fixture)
        except StopIteration:
            pass
