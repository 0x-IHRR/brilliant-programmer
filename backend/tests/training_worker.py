"""Test-only separate worker: controlled TLS endpoint, never production settings."""

import asyncio
import json
import socket
import ssl
import sys
import time
from pathlib import Path

from app.model_config import connection
from app.training import sources, submission_worker, worker
from app.training.queue import queue

control = Path(sys.argv[1])
data = json.loads(control.read_text())
original_resolve = socket.getaddrinfo
original_context = ssl.create_default_context


def resolve(host, *args, **kwargs):
    return original_resolve(
        "127.0.0.1" if host == "provider.example.com" else host, *args, **kwargs
    )


socket.getaddrinfo = resolve
connection.public_ip = lambda ip: ip == "127.0.0.1"
ssl.create_default_context = lambda: original_context(cafile=data["cert"])
sources.REFERENCES = dict.fromkeys(sources.REFERENCES, data["url"] + "/source")
connection.ATTEMPT_SECONDS = data.get("timeout", 120)
original_connect = connection.PublicBackend.connect_tcp


async def connect(self, *args, **kwargs):
    # Network barrier before socket/headers, after actual persistent budget claim.
    while (
        json.loads(control.read_text()).get("before_http")
        and worker.read_run(__import__("uuid").UUID(data["run_id"])).attempts
    ):
        Path(str(control) + ".blocked").touch()
        await asyncio.sleep(0.02)
    return await original_connect(self, *args, **kwargs)


connection.PublicBackend.connect_tcp = connect


original_stream = connection.httpcore.Response.aiter_stream


async def observed_stream(response):
    observed = bytearray()
    async for chunk in original_stream(response):
        yield chunk
        # Resumption means the real request_raw loop has already consumed this chunk.
        observed.extend(chunk)
        if (
            json.loads(control.read_text()).get("observe_usage")
            and connection.received_usage(
                bytes(observed), "text/event-stream", False
            ).get("prompt_tokens")
            == 11
        ):
            Path(str(control) + ".usage_received").touch()


connection.httpcore.Response.aiter_stream = observed_stream
original_accept = worker.accept_candidate


def accept(*args):
    while json.loads(control.read_text()).get("before_accept"):
        Path(str(control) + ".accepting").touch()
        time.sleep(0.02)
    try:
        result = original_accept(*args)
        while json.loads(control.read_text()).get("after_accept"):
            Path(str(control) + ".accepted").touch()
            time.sleep(0.02)
        return result
    finally:
        if json.loads(control.read_text()).get("observe_accept"):
            Path(str(control) + ".accept_finished").touch()


worker.accept_candidate = accept
original_finish = worker.finish


def finish(*args):
    result = original_finish(*args)
    if json.loads(control.read_text()).get("observe_finish"):
        Path(str(control) + ".finished").touch()
    return result


worker.finish = finish
original_record_submission = submission_worker.record_attempt


def record_submission(*args):
    while args[1] == "ok" and json.loads(control.read_text()).get("before_submission_ok"):
        Path(str(control) + ".submission_ok_pending").touch()
        time.sleep(0.02)
    return original_record_submission(*args)


submission_worker.record_attempt = record_submission
original_settle = submission_worker.settle
original_fail = submission_worker.fail


def fail_settle(*args):
    options = json.loads(control.read_text())
    if options.get("revoke_at_settlement") or options.get("stop_at_settlement"):
        import uuid

        from sqlmodel import Session

        from app.core.db import engine
        from app.model_config.models import ModelConfig
        from app.model_config.service import decrypt, encrypt
        from app.training.models import TrainingRun
        from app.training.submission_models import Submission

        with Session(engine) as session:
            submission = session.get(Submission, args[0])
            if options.get("stop_at_settlement"):
                submission.stop_requested = True
                submission.status, submission.code = "stopped", "stopped"
                session.add(submission)
            else:
                run = session.get(TrainingRun, submission.run_id)
                config = session.get(ModelConfig, run.user_id)
                secret = decrypt(config)
                config.version = uuid.uuid4()
                config.encrypted_key = encrypt(config, secret)
                session.add(config)
            session.commit()
    if options.get("fail_settlement"):
        raise RuntimeError("PRIVATE_SUBMISSION_SENTINEL")
    return original_settle(*args)


def fail_marker(*args):
    if json.loads(control.read_text()).get("fail_marker"):
        raise RuntimeError("PRIVATE_SUBMISSION_SENTINEL")
    return original_fail(*args)


submission_worker.settle = fail_settle
submission_worker.fail = fail_marker


async def run():
    async with queue.open_async():
        for task_name in ("training.generate", "training.check_submission", "training.evaluate", "training.concept"):
            for job in await queue.job_manager.get_stalled_jobs(
                task_name=task_name, seconds_since_heartbeat=0.5
            ):
                await queue.job_manager.retry_job(job)
        await queue.run_worker_async(
            update_heartbeat_interval=0.1,
            stalled_worker_timeout=0.5,
            fetch_job_polling_interval=0.1,
            abort_job_polling_interval=0.05,
        )


asyncio.run(run())
