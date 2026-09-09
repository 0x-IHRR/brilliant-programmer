"""Real owner UI/APIs with synthetic quality artifacts; no external model calls."""

import json
import os
import subprocess

from sqlmodel import Session, col, select

from app.core.db import engine
from app.training.models import TrainingRun
from tests.test_accounts import client
from tests.test_boss_api import seed_points
from tests.test_model_config import account, save
from tests.test_quality_api import publish, report_for

accounts = {}
auths = []
try:
    for state in ("unverified", "failed", "passed", "version_mismatch"):
        owner, auth = account()
        auths.append((owner, auth))
        config = save(auth).json()
        if state != "unverified":
            report, _ = report_for(owner, config, failed=state == "failed")
            publish(report)
        if state == "version_mismatch":
            config = save(auth, expected_version=config["version"]).json()
        if state == "failed":
            seed_points(owner, config)
        accounts[state] = auth["Authorization"].removeprefix("Bearer ")
    subprocess.run(
        ["bun", "run", "--cwd", "../frontend", "test", "quality.spec.ts"],
        env={**os.environ, "QUALITY_BROWSER_ACCOUNTS": json.dumps(accounts)},
        check=True,
    )
finally:
    for owner, auth in auths:
        with Session(engine) as session:
            pending = session.exec(
                select(TrainingRun.id).where(
                    TrainingRun.user_id == owner,
                    col(TrainingRun.status).in_(["queued", "running", "stopping"]),
                )
            ).all()
        for identity in pending:
            result = client.post(
                f"/api/v1/training/tasks/{identity}/stop", headers=auth
            )
            assert result.status_code == 200
