"""Controlled three-judgment Boss through actual HTTP, worker and browser."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

from sqlmodel import Session, select

from app.core.db import engine
from app.training.models import TrainingRun
from tests.boss_scenarios import REFERENCE, candidate, grade
from tests.test_boss_api import seed_points
from tests.test_model_config import account, save
from tests.test_training import provider, start_worker, stop_worker

with tempfile.TemporaryDirectory(prefix="boss-browser-") as directory:
    path = Path(directory)
    fixture = provider.__wrapped__(path)
    supplier = next(fixture)
    process = None
    try:
        owner, auth = account()
        config = save(auth, service_url=supplier["url"]).json()
        seed_points(owner, config)
        index = [0]

        def respond(payload):
            value = candidate(payload, index[0])
            if "new" not in json.loads(payload["messages"][1]["content"]):
                index[0] += 1
            return value

        supplier.update(candidate=respond, grading=grade, source_text=REFERENCE)
        with Session(engine) as session:
            run = session.exec(
                select(TrainingRun).where(TrainingRun.user_id == owner)
            ).first()
            identity = str(run.id)
        process, _ = start_worker(path, supplier, identity)
        subprocess.run(
            ["bun", "run", "--cwd", "../frontend", "test", "boss.spec.ts"],
            env={
                **os.environ,
                "BOSS_BROWSER_TOKEN": auth["Authorization"].removeprefix("Bearer "),
            },
            check=True,
        )
        assert len(supplier["requests"]) == 8
    finally:
        if process:
            stop_worker(process)
        try:
            next(fixture)
        except StopIteration:
            pass
