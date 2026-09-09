"""Synthetic owner, real API/DB/worker and controlled TLS; no paid service."""

import os
import subprocess
import tempfile
from pathlib import Path

from tests.test_evaluations import grading
from tests.test_model_config import account, save
from tests.test_topics import controlled
from tests.test_training import provider, start_worker, stop_worker

with tempfile.TemporaryDirectory(prefix="topic-browser-") as directory:
    path = Path(directory)
    fixture = provider.__wrapped__(path)
    supplier = next(fixture)
    _, auth = account()
    config = save(auth, service_url=supplier["url"]).json()
    supplier["candidate"] = controlled
    supplier["grading"] = grading
    process, _ = start_worker(path, supplier, "00000000-0000-0000-0000-000000000000")
    try:
        subprocess.run(
            ["bun", "run", "--cwd", "../frontend", "test", "topic.spec.ts"],
            env={
                **os.environ,
                "TOPIC_BROWSER_TOKEN": auth["Authorization"].removeprefix("Bearer "),
            },
            check=True,
        )
    finally:
        stop_worker(process)
        try:
            next(fixture)
        except StopIteration:
            pass
