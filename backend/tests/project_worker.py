"""Test-only network mapping and barriers; real queue, TLS, app workflow and DB."""

import asyncio
import json
import socket
import ssl
import sys
import time
import uuid
from pathlib import Path

from app.model_config import connection
from app.project import worker as project
from app.training import worker as training_worker  # noqa: F401
from app.training.queue import queue

control = Path(sys.argv[1])
data = json.loads(control.read_text())
original_resolve = socket.getaddrinfo
original_context = ssl.create_default_context
socket.getaddrinfo = lambda host, *args, **kwargs: original_resolve(
    "127.0.0.1" if host == "api.github.com" else host, *args, **kwargs
)
connection.public_ip = lambda ip: ip == "127.0.0.1"
ssl.create_default_context = lambda: original_context(cafile=data["cert"])
connection.ATTEMPT_SECONDS = data.get("timeout", 120)
original_connect = connection.PublicBackend.connect_tcp


async def connect(self, host, port, *args, **kwargs):
    while True:
        options = json.loads(control.read_text())
        if not (
            options.get("before_source")
            and port == 443
            or options.get("before_model")
            and port != 443
            and project.read_run(uuid.UUID(data["run_id"])).attempts
        ):
            break
        Path(str(control) + ".blocked").touch()
        await asyncio.sleep(0.02)
    return await original_connect(
        self, host, data["port"] if port == 443 else port, *args, **kwargs
    )


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
original_finish = project.finish


def finish(*args, **kwargs):
    while len(args) > 3 and json.loads(control.read_text()).get("before_finish"):
        Path(str(control) + ".finishing").touch()
        time.sleep(0.02)
    return original_finish(*args, **kwargs)


project.finish = finish
original_record = project.record_attempt


def record(*args):
    while json.loads(control.read_text()).get("before_record") == args[1]:
        Path(str(control) + ".recording").touch()
        time.sleep(0.02)
    original_record(*args)
    while json.loads(control.read_text()).get("after_record") == args[1]:
        Path(str(control) + ".recorded").touch()
        time.sleep(0.02)


project.record_attempt = record


async def main():
    async with queue.open_async():
        for job in await queue.job_manager.get_stalled_jobs(
            task_name="project.analyze", seconds_since_heartbeat=0.5
        ):
            await queue.job_manager.retry_job(job)
        Path(str(control) + ".ready").touch()
        await queue.run_worker_async(
            update_heartbeat_interval=0.1,
            stalled_worker_timeout=0.5,
            fetch_job_polling_interval=0.1,
            abort_job_polling_interval=0.05,
        )


asyncio.run(main())
