"""Three declared basic-domain UI paths, not all tiers or human quality approval."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from tests.test_model_config import account, save
from tests.test_service_data_api import BASIC, configure, launch
from tests.test_training import provider, start_worker, stop_worker, wait_run

artifacts = Path("/tmp/bp-issue-36-artifacts")
artifacts.mkdir(exist_ok=True)
for draft in BASIC[::2]:
    with tempfile.TemporaryDirectory(prefix="service-data-browser-") as directory:
        path = Path(directory)
        fixture = provider.__wrapped__(path)
        supplier = next(fixture)
        process = None
        try:
            _, auth = account()
            config = save(auth, service_url=supplier["url"]).json()
            configure(supplier, draft)
            identity = launch(auth, config, draft, "practice")
            process, _ = start_worker(path, supplier, identity)
            assert wait_run(auth, identity).json()["status"] == "completed"
            configure(supplier, draft, variant=True)
            subprocess.run(
                [
                    "bun",
                    "run",
                    "--cwd",
                    "../frontend",
                    "test",
                    "service-data.spec.ts",
                ],
                env={
                    **os.environ,
                    "SERVICE_DATA_TOKEN": auth["Authorization"].removeprefix("Bearer "),
                    "SERVICE_DATA_ORIGIN": identity,
                    "SERVICE_DATA_DRAFT": draft.model_dump_json(),
                },
                check=True,
            )
            for screenshot in Path("../frontend/test-results").glob(
                f"{draft.id}-*.png"
            ):
                shutil.copyfile(screenshot, artifacts / screenshot.name)
            assert len(supplier["requests"]) == 8
        finally:
            if process:
                stop_worker(process)
            try:
                next(fixture)
            except StopIteration:
                pass
