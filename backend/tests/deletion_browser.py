"""Real private projections and deletion receipts; only synthetic accounts/TLS."""

import json
import os
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

from sqlmodel import Session

from app.core.db import engine
from app.training.models import TrainingRun
from tests.test_accounts import client
from tests.test_evaluations import ready, start, wait
from tests.test_topics import TARGET
from tests.test_training import provider

with tempfile.TemporaryDirectory(prefix="bp31-deletion-browser-") as directory:
    cases = []
    for index in range(2):
        path = Path(directory) / str(index)
        path.mkdir()
        supplier_fixture = provider.__wrapped__(path)
        supplier = next(supplier_fixture)
        task_fixture = ready.__wrapped__(path, supplier, SimpleNamespace(param=0))
        try:
            auth, run, config, *_ = next(task_fixture)
            start(auth, run, config)
            assert wait(auth, run)["status"] == "completed"
            owner = client.get("/api/v1/users/me", headers=auth).json()["id"]
            with Session(engine) as session:
                second = TrainingRun(
                    user_id=__import__("uuid").UUID(owner),
                    config_version=__import__("uuid").UUID(config["version"]),
                    destination=config["service_url"],
                    model_id=config["model_id"],
                    target=TARGET,
                    selection={"entry": "random"},
                    status="failed",
                )
                session.add(second)
                session.commit()
                other = second.id
            cases.append(
                {
                    "token": auth["Authorization"].removeprefix("Bearer "),
                    "run": run,
                    "other": str(other),
                }
            )
            assert len(supplier["requests"]) == 3
        finally:
            try:
                next(task_fixture)
            except StopIteration:
                pass
            try:
                next(supplier_fixture)
            except StopIteration:
                pass
    subprocess.run(
        ["bun", "run", "--cwd", "../frontend", "test", "deletion.spec.ts"],
        env={**os.environ, "DELETION_BROWSER_CASES": json.dumps(cases)},
        check=True,
    )
    for case in cases:
        auth = {"Authorization": "Bearer " + case["token"]}
        assert (
            client.get(
                f"/api/v1/training/tasks/{case['run']}", headers=auth
            ).status_code
            == 410
        )
        assert (
            client.get(
                f"/api/v1/training/tasks/{case['other']}", headers=auth
            ).status_code
            == 200
        )
