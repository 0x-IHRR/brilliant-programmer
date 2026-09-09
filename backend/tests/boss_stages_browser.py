"""Highest-stage facets, actual grading/promotion and top-level continuation UI."""

import os
import subprocess
import tempfile
from pathlib import Path

from sqlmodel import Session, select

from app.core.db import engine
from app.models import User
from app.training.models import TrainingRun
from tests.stage_scenarios import REFERENCE, candidate, grade
from tests.test_boss_api import seed_points
from tests.test_model_config import account, save
from tests.test_training import provider, start_worker, stop_worker

with tempfile.TemporaryDirectory(prefix="boss-stages-browser-") as directory:
    path = Path(directory)
    fixture = provider.__wrapped__(path)
    supplier = next(fixture)
    process = None
    try:
        owner, auth = account()
        config = save(auth, service_url=supplier["url"]).json()
        seed_points(owner, config, 6000)
        with Session(engine) as session:
            user = session.get(User, owner)
            user.level = "传奇程序员"
            session.add(user)
            session.commit()
            run = session.exec(
                select(TrainingRun).where(TrainingRun.user_id == owner)
            ).first()
            identity = str(run.id)
        supplier.update(candidate=candidate, grading=grade, source_text=REFERENCE)
        process, _ = start_worker(path, supplier, identity)
        subprocess.run(
            ["bun", "run", "--cwd", "../frontend", "test", "boss-stages.spec.ts"],
            env={
                **os.environ,
                "BOSS_STAGES_BROWSER_TOKEN": auth["Authorization"].removeprefix(
                    "Bearer "
                ),
            },
            check=True,
        )
        assert len(supplier["requests"]) == 4
    finally:
        if process:
            stop_worker(process)
        try:
            next(fixture)
        except StopIteration:
            pass
