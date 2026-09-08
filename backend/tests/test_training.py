import json
import os
import ssl
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from sqlmodel import Session, select

from app.core.db import engine
from app.main import app
from app.training.models import TrainingAttempt, TrainingRun
from app.training.routes import router
from tests.test_accounts import client
from tests.test_model_config import account, save
from tests.test_model_connection import certificate

app.include_router(router, prefix="/api/v1")
with engine.begin() as db:
    TrainingRun.__table__.create(db, checkfirst=True)
    TrainingAttempt.__table__.create(db, checkfirst=True)


def candidate(payload):
    context = json.loads(payload["messages"][1]["content"])
    unique = str(uuid.uuid4())
    return {
        "target": context["target"], "catalog_version": context["catalog_version"],
        "title": "比较请求证据", "task": "根据教学材料选择有依据的下一步，并给出理由。",
        "assumptions": ["教学假设：这是一组为训练合成的观察，不是生产日志。"],
        "evidence": [{"id": "e1", "label": "教学材料", "text": "<script>window.injection=true</script> 请求尚未收到确认。", "facts": {"request": unique, "confirmed": "false"}, "citations": [{"source_id": "reference-1", "quote": context["sources"][0]["text"][:100]}]}],
        "judgments": [{"id": "j1", "prompt": "尚未确认意味着一定没有执行吗？", "options": ["不能据此确定", "一定没有执行"], "evidence_ids": ["e1"]}],
        "rubric": [{"judgment_id": "j1", "acceptable_options": [0], "reasoning": "HIDDEN_REASON：确认丢失不能证明没有执行", "evidence_ids": ["e1"], "counterexample": "HIDDEN_COUNTER：已执行但确认丢失", "help_boundary": "HIDDEN_HELP：直接指出结论属于答案提示"}],
        "variation": {"causal_condition": unique, "expected_evidence": "确认状态改变", "decision_effect": "是否需要补证"},
        "missing_evidence": [], "conflicts": [],
    }


@pytest.fixture
def provider(tmp_path):
    cert, key = certificate(tmp_path, "provider.example.com")
    state = {"mode": "ok", "requests": [], "received": threading.Event(), "release": threading.Event()}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            content = ("Controlled test reference: missing acknowledgement does not establish that an operation was not executed. " * 3).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["requests"].append(payload)
            state["received"].set()
            mode = state["mode"]
            if mode == "hold":
                state["release"].wait(10)
            status = {"auth": 401, "limited": 429, "temporary": 503}.get(mode, 200)
            value = candidate(payload)
            if mode == "forged":
                value["evidence"][0]["citations"][0]["quote"] = "Invented source quote that has never existed."
            content = json.dumps({"choices": [{"message": {"content": "" if mode == "empty" else json.dumps(value)}}], "usage": {"prompt_tokens": 11, "completion_tokens": 9, "total_tokens": 20}}).encode()
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.update(url=f"https://provider.example.com:{server.server_port}", cert=str(cert))
    yield state
    state["release"].set()
    server.shutdown()
    server.server_close()
    thread.join()


def start_run(provider):
    owner, auth = account()
    response = save(auth, service_url=provider["url"])
    assert response.status_code == 200, response.text
    response = client.post("/api/v1/training/random", headers=auth, json={"disclosure_accepted": True})
    assert response.status_code == 202, response.text
    return owner, auth, response.json()["id"]


def start_worker(tmp_path, provider, run_id, **options):
    control = tmp_path / "control.json"
    control.write_text(json.dumps({"url": provider["url"], "cert": provider["cert"], "run_id": run_id, **options}))
    log = (tmp_path / "worker.log").open("a")
    process = subprocess.Popen([sys.executable, "tests/training_worker.py", str(control)], stdout=log, stderr=log)
    log.close()
    return process, control


def stop_worker(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def wait_run(auth, run_id, statuses=("completed", "failed", "stopped")):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/training/tasks/{run_id}", headers=auth)
        assert response.status_code == 200, response.text
        if response.json()["status"] in statuses:
            return response
        time.sleep(0.05)
    raise AssertionError(f"task did not finish: {response.text}")


def test_real_worker_generation_and_hidden_answers(tmp_path, provider):
    owner, auth, run_id = start_run(provider)
    process, _ = start_worker(tmp_path, provider, run_id)
    try:
        result = wait_run(auth, run_id)
        assert result.json()["status"] == "completed", result.text
        assert len(provider["requests"]) == 1
        assert result.json()["target"]["difficulty"] == "基础"
        assert result.json()["attempts"][0]["total_tokens"] == 20
        assert "HIDDEN_" not in result.text and "acceptable_options" not in result.text
        assert result.headers["cache-control"] == "no-store"
        _, other = account()
        assert client.get(f"/api/v1/training/tasks/{run_id}", headers=other).status_code == 404
        assert client.post(f"/api/v1/training/tasks/{run_id}/stop", headers=other).status_code == 404
        assert not any("email" in str(request) for request in provider["requests"])
        with Session(engine) as session:
            run = session.get(TrainingRun, uuid.UUID(run_id))
            assert run.formal_submitted_at is None
            assert "HIDDEN_REASON" in json.dumps(run.candidate)
    finally:
        stop_worker(process)
