"""Real UI with an isolated queue worker and anonymous/model controlled TLS."""

import os
import subprocess
import tempfile
from pathlib import Path

from tests.test_model_config import account, save
from tests.test_project import provider, start_worker
from tests.test_training import stop_worker

with tempfile.TemporaryDirectory(prefix="project-browser-") as directory:
    path = Path(directory)
    fixture = provider.__wrapped__(path)
    supplier = next(fixture)
    process = None
    try:
        _, auth = account()
        assert save(auth, service_url=supplier["url"]).status_code == 200
        process, _ = start_worker(
            path, supplier, "00000000-0000-0000-0000-000000000000"
        )
        subprocess.run(
            ["bun", "run", "--cwd", "../frontend", "test", "project.spec.ts"],
            env={
                **os.environ,
                "PROJECT_BROWSER_TOKEN": auth["Authorization"].removeprefix("Bearer "),
            },
            check=True,
        )
        assert len(supplier["requests"]) == 2
    finally:
        if process:
            stop_worker(process)
        try:
            next(fixture)
        except StopIteration:
            pass
