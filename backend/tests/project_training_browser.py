"""Real project-route UI against isolated PostgreSQL and controlled TLS only."""

import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path

from sqlmodel import Session

from app.core.db import engine
from app.project.models import ProjectRun
from tests.test_evaluations import grading
from tests.test_model_config import account, save
from tests.test_project_public_training import public_material, respond
from tests.test_training import provider, start_worker, stop_worker

with tempfile.TemporaryDirectory(prefix="bp23-browser-") as directory:
    root = Path(directory)
    fixture = provider.__wrapped__(root)
    supplier = next(fixture)
    owner, auth = account()
    config = save(auth, service_url=supplier["url"]).json()
    snapshot, mapped, _ = public_material()
    with Session(engine) as session:
        project = ProjectRun(
            user_id=owner,
            url="https://github.com/pallets/itsdangerous",
            config_version=uuid.UUID(config["version"]),
            destination=supplier["url"],
            model_id=config["model_id"],
            status="completed",
            code="ok",
            snapshot=snapshot.model_dump(mode="json"),
            project_map=mapped.model_dump(mode="json"),
        )
        session.add(project)
        session.commit()
        project_id = str(project.id)

    def reply(payload):
        data = json.loads(payload["messages"][1]["content"])
        if "confirmed_topic" in data:
            assert (
                data["confirmed_topic"]["focus"]
                == "重点核对 age 等于60与61的边界，不声称执行过代码"
            )
        return respond(payload)

    supplier["candidate"] = reply

    def grade(context):
        result = grading(context)
        result["items"][0]["grounding"][0].update(fact="age", value="60")
        result["items"][0]["reason_claims"][0]["interpreted_fact_value"] = "60"
        return result

    supplier["grading"] = grade
    process, _ = start_worker(root, supplier, "00000000-0000-0000-0000-000000000000")
    try:
        subprocess.run(
            ["bun", "run", "--cwd", "../frontend", "test", "project-training.spec.ts"],
            check=True,
            env={
                **os.environ,
                "PROJECT_TRAINING_TOKEN": auth["Authorization"].removeprefix("Bearer "),
                "PROJECT_TRAINING_RUN_ID": project_id,
            },
        )
    finally:
        stop_worker(process)
        try:
            next(fixture)
        except StopIteration:
            pass
