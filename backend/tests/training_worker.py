"""Test-only separate worker: controlled TLS endpoint, never production settings."""

import asyncio
import json
import socket
import ssl
import sys
import time
from pathlib import Path

from app.model_config import connection
from app.training import sources, worker
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


original_accept = worker.accept_candidate


def accept(*args):
    while json.loads(control.read_text()).get("before_accept"):
        Path(str(control) + ".accepting").touch()
        time.sleep(0.02)
    return original_accept(*args)


worker.accept_candidate = accept


async def run():
    async with queue.open_async():
        for job in await queue.job_manager.get_stalled_jobs(
            task_name="training.generate", seconds_since_heartbeat=0.5
        ):
            await queue.job_manager.retry_job(job)
        await queue.run_worker_async(
            update_heartbeat_interval=0.1,
            stalled_worker_timeout=0.5,
            fetch_job_polling_interval=0.1,
            abort_job_polling_interval=0.05,
        )


asyncio.run(run())
