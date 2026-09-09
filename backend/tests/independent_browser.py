"""Actual UI + API + worker; synthetic frozen origin and controlled TLS provider."""

import os
import subprocess
import tempfile
from pathlib import Path

from tests.test_guided import frozen
from tests.test_independent_api import controlled_grading, origin
from tests.test_practices import guided_coach
from tests.test_training import provider, start_worker, stop_worker

with tempfile.TemporaryDirectory(prefix="independent-browser-") as directory:
    path = Path(directory)
    fixture = provider.__wrapped__(path)
    supplier = next(fixture)
    process = None
    try:
        auth, identity, _, _ = origin.__wrapped__(supplier, frozen.__wrapped__())
        supplier["grading"], supplier["coach"] = controlled_grading, guided_coach
        process, _ = start_worker(path, supplier, str(identity))
        subprocess.run(
            ["bun", "run", "--cwd", "../frontend", "test", "independent.spec.ts"],
            env={
                **os.environ,
                "INDEPENDENT_BROWSER_TOKEN": auth["Authorization"].removeprefix(
                    "Bearer "
                ),
                "INDEPENDENT_BROWSER_ORIGIN": str(identity),
            },
            check=True,
        )
        assert (
            len(supplier["requests"]) == 5
        )  # generation, comparison, relevance, grading, hint inspection
    finally:
        if process:
            stop_worker(process)
        try:
            next(fixture)
        except StopIteration:
            pass
