"""Actual five-round controlled evidence, followed by authenticated map UI."""

import os
import subprocess
import tempfile
import time
from pathlib import Path

from tests.test_accounts import client
from tests.test_capability_evidence_api import (
    test_five_actual_new_cases_verify_fail_and_recover,
)
from tests.test_independent_api import frozen, origin
from tests.test_training import provider

with tempfile.TemporaryDirectory(prefix="capability-browser-") as directory:
    path = Path(directory)
    fixture = provider.__wrapped__(path)
    supplier = next(fixture)
    try:
        case = frozen.__wrapped__()
        owner = origin.__wrapped__(supplier, case)
        test_five_actual_new_cases_verify_fail_and_recover(path, supplier, owner, case)
        start = time.perf_counter()
        result = client.get("/api/v1/capabilities/evidence", headers=owner[0])
        assert result.status_code == 200
        print(  # noqa: T201 -- synthetic projection timing
            "five-original projection milliseconds",
            round((time.perf_counter() - start) * 1000, 2),
        )  # noqa: T201
        subprocess.run(
            [
                "bun",
                "run",
                "--cwd",
                "../frontend",
                "test",
                "capability-evidence.spec.ts",
            ],
            env={
                **os.environ,
                "CAPABILITY_BROWSER_TOKEN": owner[0]["Authorization"].removeprefix(
                    "Bearer "
                ),
                "CAPABILITY_BROWSER_ID": case[0].target.capability_id,
            },
            check=True,
        )
    finally:
        try:
            next(fixture)
        except StopIteration:
            pass
