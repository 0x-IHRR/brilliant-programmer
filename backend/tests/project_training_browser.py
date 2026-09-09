"""Real project-route UI against isolated PostgreSQL and controlled TLS only."""

import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path

from sqlmodel import Session, select

from app.core.db import engine
from app.project.models import ProjectRun
from app.training.models import TrainingRun
from app.training.topic_models import TopicJob
from tests.test_evaluations import grading
from tests.test_model_config import account, save
from tests.test_project_public_training import public_material, respond
from tests.test_training import provider, start_worker, stop_worker, wait_run

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
        other = ProjectRun(
            user_id=owner,
            url="https://github.com/pallets/itsdangerous?second-owned-project",
            config_version=uuid.UUID(config["version"]),
            destination=supplier["url"],
            model_id=config["model_id"],
            status="completed",
            code="ok",
            snapshot=snapshot.model_dump(mode="json"),
            project_map=mapped.model_dump(mode="json"),
        )
        session.add(other)
        session.commit()
        other_id = str(other.id)

    generated = 0

    def reply(payload):
        global generated
        data = json.loads(payload["messages"][1]["content"])
        if "confirmed_topic" in data:
            assert (
                data["confirmed_topic"]["focus"]
                == "重点核对 age 等于60与61的边界，不声称执行过代码"
            )
        result = respond(payload)
        if "case" in result:
            generated += 1
            if generated == 2:
                # A second accepted request needs a real different scenario;
                # the shared ordinary path correctly rejects exact repeats.
                case = result["case"]
                case["evidence"][0]["facts"]["age"] = "61"
                case["evidence"][0]["text"] = (
                    "教学假设：受控时钟让 age 恰为61秒，max_age 为60秒。"
                )
                case["judgments"][0]["prompt"] = (
                    "基于这些前提，age=61 的边界测试应期待什么？"
                )
                case["rubric"][0].update(
                    acceptable_options=[1],
                    reasoning="61大于60，源码过期分支应抛出 SignatureExpired。",
                    counterexample="age=60不满足严格大于，应返回原值。",
                )
                case["variation"] = {
                    "causal_condition": "将 age 从61改60",
                    "expected_evidence": "不进入大于分支并返回原值",
                    "decision_effect": "从异常断言改为返回值断言",
                }
        return result

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
                "PROJECT_TRAINING_OTHER_ID": other_id,
            },
        )
        with Session(engine) as session:
            runs = session.exec(
                select(TrainingRun).where(TrainingRun.user_id == owner)
            ).all()
            assert len(runs) == 2
            identities = [str(run.id) for run in runs]
        for identity in identities:
            assert wait_run(auth, identity).json()["status"] == "completed"
        assert len(supplier["requests"]) == 8
        with Session(engine) as session:
            assert (
                len(
                    session.exec(
                        select(TopicJob).where(TopicJob.user_id == owner)
                    ).all()
                )
                == 1
            )
    finally:
        stop_worker(process)
        try:
            next(fixture)
        except StopIteration:
            pass
