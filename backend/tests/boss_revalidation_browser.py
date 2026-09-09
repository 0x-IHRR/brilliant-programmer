"""Actual accepted correction, same-stage UI practice, and retained history."""

import os
import subprocess
import tempfile
from pathlib import Path

from tests import boss_scenarios
from tests.test_boss_api import answer, seed_points, start
from tests.test_boss_revalidation import access, corrected
from tests.test_evaluations import wait
from tests.test_model_config import account, save
from tests.test_reviews import start as review_start
from tests.test_reviews import wait as review_wait
from tests.test_submissions import wait_submission
from tests.test_training import provider, start_worker, stop_worker, wait_run

with tempfile.TemporaryDirectory(prefix="boss-revalidation-browser-") as directory:
    path = Path(directory)
    fixture = provider.__wrapped__(path)
    supplier = next(fixture)
    process = None
    try:
        owner, auth = account()
        config = save(auth, service_url=supplier["url"]).json()
        seed_points(owner, config)
        supplier.update(
            candidate=boss_scenarios.candidate,
            grading=boss_scenarios.grade,
            review=corrected,
            source_text=boss_scenarios.REFERENCE,
        )
        identity = start(auth, config).json()["id"]
        process, _ = start_worker(path, supplier, identity)
        assert wait_run(auth, identity).json()["status"] == "completed"
        answer(auth, identity, config)
        assert wait_submission(auth, identity)["awarded_points"] == 10
        assert wait(auth, identity)["status"] == "completed"
        review_start(auth, identity, config)
        assert review_wait(auth, identity)["decision"] == "corrected"
        requirement = access(auth)["revalidations"][0]
        supplier["candidate"] = lambda payload: boss_scenarios.candidate(payload, 1)
        subprocess.run(
            ["bun", "run", "--cwd", "../frontend", "test", "boss-revalidation.spec.ts"],
            env={
                **os.environ,
                "REVALIDATION_BROWSER_TOKEN": auth["Authorization"].removeprefix(
                    "Bearer "
                ),
                "REVALIDATION_PROMOTION": requirement["promotion_id"],
            },
            check=True,
        )
        assert len(supplier["requests"]) == 10
        state = access(auth)
        assert state["level"] == "初级程序员" and state["points"] == 120
        assert [e["kind"] for e in state["revalidations"][0]["events"]] == [
            "required",
            "resolved",
            "required",
        ]
    finally:
        if process:
            stop_worker(process)
        try:
            next(fixture)
        except StopIteration:
            pass
