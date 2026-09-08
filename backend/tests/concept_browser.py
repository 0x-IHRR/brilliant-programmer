"""Concept UI with a real API/DB/worker and controlled TLS model, serial only."""

import os
import subprocess
import tempfile
from pathlib import Path

from tests.test_concepts import coach
from tests.test_training import provider, start_run, start_worker, stop_worker, wait_run

with tempfile.TemporaryDirectory(prefix="concept-browser-") as directory:
    path = Path(directory)
    fixture = provider.__wrapped__(path)
    supplier = next(fixture)
    supplier["coach"] = coach
    process = None
    try:
        _, auth, identity = start_run(supplier)
        process, _ = start_worker(path, supplier, identity)
        assert wait_run(auth, identity).json()["status"] == "completed"
        subprocess.run(
            ["bun", "run", "--cwd", "../frontend", "test", "concept.spec.ts"],
            env={
                **os.environ,
                "CONCEPT_BROWSER_TOKEN": auth["Authorization"].removeprefix("Bearer "),
            },
            check=True,
        )
        assert len(supplier["requests"]) == 5
    finally:
        if process:
            stop_worker(process)
        try:
            next(fixture)
        except StopIteration:
            pass
