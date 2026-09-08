import json
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
from sqlmodel import Session

from app.core.db import engine
from app.training.models import TrainingRun
from tests.test_accounts import client
from tests.test_model_config import account, save
from tests.test_model_connection import certificate


def candidate(payload):
    context = json.loads(payload["messages"][1]["content"])
    unique = str(uuid.uuid4())
    return {
        "target": context["target"],
        "catalog_version": context["catalog_version"],
        "title": "比较请求证据",
        "task": "根据教学材料选择有依据的下一步，并给出理由。",
        "assumptions": ["教学假设：这是一组为训练合成的观察，不是生产日志。"],
        "evidence": [
            {
                "id": "e1",
                "label": "教学材料",
                "text": "<script>window.injection=true</script> 请求尚未收到确认。",
                "facts": {"request": unique, "confirmed": "false"},
                "citations": [
                    {
                        "source_id": "reference-1",
                        "quote": context["sources"][0]["text"][:100],
                    }
                ],
            }
        ],
        "judgments": [
            {
                "id": "j1",
                "kind": "choice",
                "prompt": "尚未确认意味着一定没有执行吗？",
                "options": ["不能据此确定", "一定没有执行"],
                "evidence_ids": ["e1"],
            }
        ],
        "rubric": [
            {
                "judgment_id": "j1",
                "acceptable_options": [0],
                "reasoning": "HIDDEN_REASON：确认丢失不能证明没有执行",
                "evidence_ids": ["e1"],
                "counterexample": "HIDDEN_COUNTER：已执行但确认丢失",
                "help_boundary": "HIDDEN_HELP：直接指出结论属于答案提示",
            }
        ],
        "variation": {
            "causal_condition": unique,
            "expected_evidence": "确认状态改变",
            "decision_effect": "是否需要补证",
        },
        "missing_evidence": [],
        "conflicts": [],
    }


@pytest.fixture
def provider(tmp_path):
    cert, key = certificate(tmp_path, "provider.example.com")
    state = {
        "mode": "ok",
        "requests": [],
        "received": threading.Event(),
        "release": threading.Event(),
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            content = (
                "Controlled test reference: missing acknowledgement does not establish that an operation was not executed. "
                * 3
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["requests"].append(payload)
            state["received"].set()
            mode = state["modes"].pop(0) if state.get("modes") else state["mode"]
            if mode == "hold":
                state["release"].wait(10)
            if mode == "partial_usage":
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Content-Length", "100000")
                    self.end_headers()
                    self.wfile.write(
                        b'data: {"choices":[],"usage":{"prompt_tokens":11,"total_tokens":20}}\n\n'
                    )
                    self.wfile.flush()
                    state["release"].wait(10)
                except BrokenPipeError, ConnectionResetError, ssl.SSLError:
                    pass
                return
            status = {"auth": 401, "limited": 429, "temporary": 503}.get(mode, 200)
            context_data = json.loads(payload["messages"][1]["content"])
            if context_data.get("purpose") == "evidence_feedback":
                value = state["grading"](context_data)
            elif context_data.get("purpose") == "reason_relevance":
                value = {
                    "items": [
                        {
                            "judgment_id": a["judgment_id"],
                            "status": state.get("relevance_labels", {}).get(
                                a["reason"], state.get("relevance", "related")
                            ),
                        }
                        for a in context_data["answers"]
                    ]
                }
                if mode == "bad_relevance":
                    value["items"][0]["judgment_id"] = "unknown-judgment"
            else:
                value = candidate(payload)
                if state.get("all_kinds"):
                    value["judgments"] += [
                        {
                            "id": "j2",
                            "kind": "order",
                            "prompt": "安排验证步骤",
                            "options": ["查看请求记录", "判断执行状态", "验证结果"],
                            "evidence_ids": ["e1"],
                        },
                        {
                            "id": "j3",
                            "kind": "prediction",
                            "prompt": "如果确认迟到，你预测什么？",
                            "options": ["执行过", "未执行"],
                            "evidence_ids": ["e1"],
                        },
                    ]
                    value["rubric"] += [
                        {
                            **value["rubric"][0],
                            "judgment_id": "j2",
                            "acceptable_options": [],
                            "acceptable_orders": [[0, 1, 2]],
                        },
                        {
                            **value["rubric"][0],
                            "judgment_id": "j3",
                            "acceptable_options": [],
                            "acceptable_predictions": ["确认晚到可能已经执行"],
                        },
                    ]
            if mode == "forged":
                value["evidence"][0]["citations"][0]["quote"] = (
                    "Invented source quote that has never existed."
                )
            content = json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "" if mode == "empty" else json.dumps(value)
                            }
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 11,
                        "completion_tokens": 9,
                        "total_tokens": 20,
                    },
                }
            ).encode()
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            except BrokenPipeError, ConnectionResetError, ssl.SSLError:
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.update(
        url=f"https://provider.example.com:{server.server_port}", cert=str(cert)
    )
    yield state
    state["release"].set()
    server.shutdown()
    server.server_close()
    thread.join()


def start_run(provider):
    owner, auth = account()
    response = save(auth, service_url=provider["url"])
    assert response.status_code == 200, response.text
    response = client.post(
        "/api/v1/training/random",
        headers=auth,
        json={
            "disclosure_accepted": True,
            "expected_config_version": response.json()["version"],
        },
    )
    assert response.status_code == 202, response.text
    return owner, auth, response.json()["id"]


def start_worker(tmp_path, provider, run_id, **options):
    control = tmp_path / "control.json"
    control.write_text(
        json.dumps(
            {
                "url": provider["url"],
                "cert": provider["cert"],
                "run_id": run_id,
                **options,
            }
        )
    )
    log = (tmp_path / "worker.log").open("a")
    process = subprocess.Popen(
        [sys.executable, "tests/training_worker.py", str(control)],
        stdout=log,
        stderr=log,
    )
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
        assert (
            client.get(f"/api/v1/training/tasks/{run_id}", headers=other).status_code
            == 404
        )
        assert (
            client.post(
                f"/api/v1/training/tasks/{run_id}/stop", headers=other
            ).status_code
            == 404
        )
        assert not any("email" in str(request) for request in provider["requests"])
        with Session(engine) as session:
            run = session.get(TrainingRun, uuid.UUID(run_id))
            assert run.formal_submitted_at is None
            assert "HIDDEN_REASON" in json.dumps(run.candidate)
    finally:
        stop_worker(process)


@pytest.mark.parametrize(
    "mode,expected,attempts",
    [
        ("empty", "invalid_response", 2),
        ("forged", "invalid_candidate", 2),
        ("auth", "authentication", 1),
        ("limited", "rate_limited", 3),
        ("temporary", "temporary_service", 3),
    ],
)
def test_worker_bounded_failure(tmp_path, provider, mode, expected, attempts):
    provider["mode"] = mode
    _, auth, run_id = start_run(provider)
    process, _ = start_worker(tmp_path, provider, run_id)
    try:
        result = wait_run(auth, run_id).json()
        assert result["status"] == "failed" and result["code"] == expected, result
        assert result["case"] is None
        assert len(provider["requests"]) == attempts == len(result["attempts"])
    finally:
        stop_worker(process)


def test_stop_before_http_does_not_send_old_key(tmp_path, provider):
    _, auth, run_id = start_run(provider)
    process, control = start_worker(tmp_path, provider, run_id, before_http=True)
    try:
        blocked = Path(str(control) + ".blocked")
        deadline = time.monotonic() + 8
        while not blocked.exists() and time.monotonic() < deadline:
            time.sleep(0.03)
        assert blocked.exists()
        with ThreadPoolExecutor() as pool:
            stop = pool.submit(
                client.post, f"/api/v1/training/tasks/{run_id}/stop", headers=auth
            )
            result = stop.result(timeout=5)
        assert result.status_code == 200, result.text
        assert result.json()["status"] == "stopped"
        assert provider["requests"] == []
        value = json.loads(control.read_text())
        value["before_http"] = False
        control.write_text(json.dumps(value))
        time.sleep(0.25)
        assert provider["requests"] == []
        assert result.json()["attempts"][0]["total_tokens"] is None
    finally:
        stop_worker(process)
    process, _ = start_worker(tmp_path, provider, run_id)
    try:
        time.sleep(0.3)
        assert wait_run(auth, run_id).json()["status"] == "stopped"
        assert provider["requests"] == []
    finally:
        stop_worker(process)


def test_killed_worker_recovers_same_budget_and_unknown_usage(tmp_path, provider):
    provider["mode"] = "hold"
    _, auth, run_id = start_run(provider)
    process, _ = start_worker(tmp_path, provider, run_id)
    try:
        assert provider["received"].wait(8)
        process.kill()
        process.wait()
        time.sleep(0.7)
        provider["mode"] = "ok"
        process, _ = start_worker(tmp_path, provider, run_id)
        result = wait_run(auth, run_id).json()
        assert result["status"] == "completed", result
        assert len(result["attempts"]) == len(provider["requests"]) == 2
        assert result["attempts"][0]["code"] == "unknown"
        assert result["attempts"][0]["total_tokens"] is None
        assert result["attempts"][1]["total_tokens"] == 20
    finally:
        provider["release"].set()
        stop_worker(process)


def test_stop_inflight_cancels_and_repeat_dispatch_preserves_result(tmp_path, provider):
    provider["mode"] = "hold"
    _, auth, run_id = start_run(provider)
    process, _ = start_worker(tmp_path, provider, run_id)
    try:
        assert provider["received"].wait(8)
        result = client.post(f"/api/v1/training/tasks/{run_id}/stop", headers=auth)
        assert result.status_code == 200 and result.json()["status"] == "stopped"
        provider["release"].set()
        time.sleep(0.2)
        assert len(provider["requests"]) == 1
        assert (
            client.post(f"/api/v1/training/tasks/{run_id}/stop", headers=auth).json()[
                "status"
            ]
            == "stopped"
        )
    finally:
        stop_worker(process)


def test_six_total_attempts_with_one_correction(tmp_path, provider):
    provider["modes"] = [
        "temporary",
        "temporary",
        "forged",
        "temporary",
        "temporary",
        "forged",
    ]
    _, auth, run_id = start_run(provider)
    process, _ = start_worker(tmp_path, provider, run_id)
    try:
        result = wait_run(auth, run_id).json()
        assert result["status"] == "failed" and result["code"] == "invalid_candidate", (
            result
        )
        assert len(provider["requests"]) == len(result["attempts"]) == 6
        with Session(engine) as session:
            run = session.get(TrainingRun, uuid.UUID(run_id))
            assert (run.attempts, run.generation, run.generation_attempts) == (6, 1, 3)
    finally:
        stop_worker(process)


def test_repeated_kill_cannot_reset_single_call_budget(tmp_path, provider):
    provider["mode"] = "hold"
    _, auth, run_id = start_run(provider)
    process = None
    try:
        for expected in range(1, 4):
            provider["received"].clear()
            process, _ = start_worker(tmp_path, provider, run_id)
            assert provider["received"].wait(8)
            assert len(provider["requests"]) == expected
            process.kill()
            process.wait()
            time.sleep(0.7)
        process, _ = start_worker(tmp_path, provider, run_id)
        result = wait_run(auth, run_id).json()
        assert result["status"] == "failed" and result["code"] == "budget_exhausted"
        assert len(provider["requests"]) == len(result["attempts"]) == 3
        assert all(
            a["code"] == "unknown" and a["total_tokens"] is None
            for a in result["attempts"]
        )
    finally:
        provider["release"].set()
        if process:
            stop_worker(process)


def test_duplicate_dispatch_has_no_second_external_call(tmp_path, provider):
    import procrastinate

    from app.training.queue import DSN
    from app.training.worker import generate_training

    _, auth, run_id = start_run(provider)
    process, _ = start_worker(tmp_path, provider, run_id)
    try:
        result = wait_run(auth, run_id).json()
        assert result["status"] == "completed"
        queue = procrastinate.App(
            connector=procrastinate.SyncPsycopgConnector(conninfo=DSN)
        )
        task = queue.task(name="training.generate")(generate_training.func)
        with Session(engine) as session:
            task.configure(
                connection=session.connection().connection.driver_connection,
                lock=run_id,
            ).defer(run_id=run_id)
            session.commit()
        time.sleep(0.4)
        assert len(provider["requests"]) == 1
        assert wait_run(auth, run_id).json()["case"] == result["case"]
        from app.training.schema import Source
        from app.training.worker import read_run, save_sources

        original = read_run(uuid.UUID(run_id)).sources
        delayed = [
            Source.model_validate(source).model_copy(
                update={"text": "late unrelated snapshot"}
            )
            for source in original
        ]
        save_sources(uuid.UUID(run_id), delayed)
        assert read_run(uuid.UUID(run_id)).sources == original
    finally:
        stop_worker(process)


def test_config_revocation_blocks_old_retry(tmp_path, provider):
    provider["mode"] = "temporary"
    _, auth, run_id = start_run(provider)
    process, _ = start_worker(tmp_path, provider, run_id)
    try:
        assert provider["received"].wait(8)
        config = client.get("/api/v1/model-config", headers=auth).json()
        assert (
            client.delete(
                "/api/v1/model-config",
                headers=auth,
                params={"expected_version": config["version"]},
            ).status_code
            == 204
        )
        result = wait_run(auth, run_id).json()
        assert result["code"] == "configuration_revoked"
        assert len(provider["requests"]) == 1
    finally:
        stop_worker(process)


def test_timeout_preserves_partial_sse_usage(tmp_path, provider):
    provider["mode"] = "partial_usage"
    _, auth, run_id = start_run(provider)
    process, _ = start_worker(tmp_path, provider, run_id, timeout=0.3)
    try:
        result = wait_run(auth, run_id).json()
        assert result["status"] == "failed" and result["code"] == "timeout", result
        assert len(provider["requests"]) == 3
        assert all(
            a["prompt_tokens"] == 11
            and a["total_tokens"] == 20
            and a["completion_tokens"] is None
            for a in result["attempts"]
        )
    finally:
        provider["release"].set()
        stop_worker(process)


def test_stop_preserves_late_verified_candidate_and_usage(tmp_path, provider):
    _, auth, run_id = start_run(provider)
    process, control = start_worker(tmp_path, provider, run_id, before_accept=True)
    try:
        deadline = time.monotonic() + 8
        while (
            not Path(str(control) + ".accepting").exists()
            and time.monotonic() < deadline
        ):
            time.sleep(0.03)
        assert Path(str(control) + ".accepting").exists()
        result = client.post(f"/api/v1/training/tasks/{run_id}/stop", headers=auth)
        assert result.status_code == 200 and result.json()["status"] == "stopped"
        data = json.loads(control.read_text())
        data["before_accept"] = False
        control.write_text(json.dumps(data))
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = wait_run(auth, run_id).json()
            if result["case"]:
                break
            time.sleep(0.03)
        assert result["status"] == "stopped" and result["case"] is not None
        assert result["attempts"][0]["total_tokens"] == 20
        assert len(provider["requests"]) == 1
    finally:
        data = json.loads(control.read_text())
        data["before_accept"] = False
        control.write_text(json.dumps(data))
        stop_worker(process)


def test_seed_replay_concurrent_start_and_formal_submission_boundary(provider):
    import random
    from datetime import UTC, datetime

    _, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    payload = {
        "disclosure_accepted": True,
        "expected_config_version": config["version"],
    }
    with ThreadPoolExecutor() as pool:
        first, second = [
            future.result()
            for future in [
                pool.submit(
                    client.post, "/api/v1/training/random", headers=auth, json=payload
                )
                for _ in range(2)
            ]
        ]
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    run_id = first.json()["id"]
    with Session(engine) as session:
        run = session.get(TrainingRun, uuid.UUID(run_id))
        assert (
            random.Random(run.selection["seed"]).choice(run.selection["candidates"])
            == run.target
        )
        assert run.formal_submitted_at is None
    assert (
        client.post(f"/api/v1/training/tasks/{run_id}/stop", headers=auth).status_code
        == 200
    )
    changed = client.post(
        "/api/v1/training/random",
        headers=auth,
        json={**payload, "previous_run_id": run_id},
    )
    assert changed.status_code == 202
    assert changed.json()["target"] != first.json()["target"]
    assert (
        client.post(
            f"/api/v1/training/tasks/{changed.json()['id']}/stop", headers=auth
        ).status_code
        == 200
    )
    with Session(engine) as session:
        run = session.get(TrainingRun, uuid.UUID(run_id))
        run.formal_submitted_at = datetime.now(UTC)
        session.add(run)
        session.commit()
    assert (
        client.post("/api/v1/training/random", headers=auth, json=payload).status_code
        == 409
    )
    assert provider["requests"] == []


@pytest.mark.parametrize(
    "code,generation", [("authentication", 0), ("invalid_candidate", 1)]
)
def test_recovery_after_known_outcome_never_reopens_finished_budget(
    tmp_path, provider, code, generation
):
    from app.training.models import TrainingAttempt

    _, auth, run_id = start_run(provider)
    with Session(engine) as session:
        run = session.get(TrainingRun, uuid.UUID(run_id))
        run.attempts, run.generation, run.generation_attempts = (
            1 + generation,
            generation,
            1,
        )
        run.status = "running"
        session.add(run)
        session.add(
            TrainingAttempt(
                run_id=run.id, number=run.attempts, generation=generation, code=code
            )
        )
        session.commit()
    process, _ = start_worker(tmp_path, provider, run_id)
    try:
        result = wait_run(auth, run_id).json()
        assert result["status"] == "failed" and result["code"] == code
        assert provider["requests"] == []
    finally:
        stop_worker(process)
