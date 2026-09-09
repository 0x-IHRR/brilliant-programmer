"""Real formal history and model worker, two browser devices change preferences."""

import os
import subprocess
import tempfile
from pathlib import Path

from tests.test_random_api import formal
from tests.test_submissions import ready
from tests.test_training import provider

with tempfile.TemporaryDirectory(prefix="random-browser-") as directory:
    path = Path(directory)
    fixture = provider.__wrapped__(path)
    supplier = next(fixture)
    owner_fixture = ready.__wrapped__(path, supplier)
    owner = next(owner_fixture)
    try:
        formal(owner)
        subprocess.run(
            ["bun", "run", "--cwd", "../frontend", "test", "random.spec.ts"],
            env={
                **os.environ,
                "RANDOM_BROWSER_TOKEN": owner[1]["Authorization"].removeprefix(
                    "Bearer "
                ),
                "RANDOM_ORIGINAL_RUN": owner[2],
            },
            check=True,
        )
    finally:
        try:
            next(owner_fixture)
        except StopIteration:
            pass
        try:
            next(fixture)
        except StopIteration:
            pass
