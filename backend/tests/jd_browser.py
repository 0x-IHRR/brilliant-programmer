"""Real JD UI/API with controlled TLS, no paid model or human quality claim."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

from tests.test_evaluations import grading
from tests.test_jd_rules import sample
from tests.test_model_config import account, save
from tests.test_topics import controlled
from tests.test_training import provider, start_worker, stop_worker

with tempfile.TemporaryDirectory(prefix="jd-browser-") as directory:
    path = Path(directory)
    fixture = provider.__wrapped__(path)
    supplier = next(fixture)
    _, auth = account()
    save(auth, service_url=supplier["url"])

    def respond(payload):
        context = json.loads(payload["messages"][1]["content"])
        if "jd_text" in context.get("context", {}):
            if "candidate" in context["context"]:
                return {
                    "accepted": True,
                    "explanation": "受控材料逐字引用与岗位映射一致",
                }
            if context["context"]["jd_text"] == "欢迎加入我们":
                return {
                    "kind": "no_requirements",
                    "message": "请补充具体岗位要求",
                    "roles": [],
                }
            return sample()[1].model_dump(mode="json")
        if "confirmed_topic" in context:
            assert context["confirmed_topic"]["focus"] == "先查处理日志与持久结果，再判断重试是否安全"
        return controlled(payload)

    supplier["candidate"] = respond
    supplier["grading"] = grading
    process, _ = start_worker(path, supplier, "00000000-0000-0000-0000-000000000000")
    try:
        subprocess.run(
            ["bun", "run", "--cwd", "../frontend", "test", "jd.spec.ts"],
            env={
                **os.environ,
                "JD_BROWSER_TOKEN": auth["Authorization"].removeprefix("Bearer "),
            },
            check=True,
        )
    finally:
        stop_worker(process)
        try:
            next(fixture)
        except StopIteration:
            pass
