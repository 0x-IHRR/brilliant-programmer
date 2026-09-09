"""Serial guided-practice browser flow through real API/DB/worker and controlled TLS."""

import os
import subprocess
import tempfile
from pathlib import Path

from tests.test_practices import guided_coach, safe_case
from tests.test_training import provider, start_run, start_worker, stop_worker, wait_run

with tempfile.TemporaryDirectory(prefix="guided-browser-") as directory:
    path = Path(directory)
    fixture = provider.__wrapped__(path)
    supplier = next(fixture)
    supplier["candidate"], supplier["coach"], supplier["all_kinds"] = (
        safe_case,
        guided_coach,
        True,
    )
    process = None
    try:
        _, auth, identity = start_run(supplier)
        process, _ = start_worker(path, supplier, identity)
        assert wait_run(auth, identity).json()["status"] == "completed"
        subprocess.run(
            ["bun", "run", "--cwd", "../frontend", "test", "guided.spec.ts"],
            env={
                **os.environ,
                "GUIDED_BROWSER_TOKEN": auth["Authorization"].removeprefix("Bearer "),
                "GUIDED_BROWSER_RUN": identity,
            },
            check=True,
        )
        assert (
            len(supplier["requests"]) == 4
        )  # generation, hint check, demo check, practice relevance
    finally:
        if process:
            stop_worker(process)
        try:
            next(fixture)
        except StopIteration:
            pass
