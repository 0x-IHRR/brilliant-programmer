"""Run the real browser against a separate worker and controlled TLS supplier."""

import os
import subprocess
import tempfile
from pathlib import Path

from tests.test_evaluations import grading
from tests.test_model_config import account, save
from tests.test_training import provider, start_worker, stop_worker

with tempfile.TemporaryDirectory(prefix="training-browser-") as directory:
    path = Path(directory)
    fixture = provider.__wrapped__(path)
    supplier = next(fixture)
    supplier["all_kinds"] = True
    supplier["grading"] = lambda context: grading(context, "unclear")
    supplier["relevance_labels"] = {"午饭准备吃饺子。": "unrelated", "我还是不明白。": "unclear", "仍旧不明白。": "unclear"}
    process = None
    try:
        _, unconfigured_auth = account()
        _, auth = account()
        assert save(auth, service_url=supplier["url"]).status_code == 200
        process, _ = start_worker(
            path, supplier, "00000000-0000-0000-0000-000000000000"
        )
        environment = {
            **os.environ,
            "TRAINING_BROWSER_TOKEN": auth["Authorization"].removeprefix("Bearer "),
            "TRAINING_UNCONFIGURED_TOKEN": unconfigured_auth[
                "Authorization"
            ].removeprefix("Bearer "),
        }
        subprocess.run(
            ["bun", "run", "--cwd", "../frontend", "test", "training.spec.ts"],
            env=environment,
            check=True,
        )
        assert len(supplier["requests"]) >= 1
    finally:
        if process:
            stop_worker(process)
        try:
            next(fixture)
        except StopIteration:
            pass
