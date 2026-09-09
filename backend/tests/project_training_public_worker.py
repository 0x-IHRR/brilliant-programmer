"""Online witness: real public-source transport, only the fake model is loopback.

Never imported by production. No DNS/IP gate changes for GitHub or other hosts.
TLS still verifies hostnames against system trust plus the local provider CA.
"""

import asyncio
import json
import ssl
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpcore

from app.model_config.connection import PublicBackend
from app.training import worker  # noqa: F401 -- registers all production tasks
from app.training.queue import queue

data = json.loads(Path(sys.argv[1]).read_text())
destination = urlsplit(data["url"])
assert destination.hostname == "provider.example.com" and destination.port
original_connect = PublicBackend.connect_tcp
original_context = ssl.create_default_context


async def connect(self, host, port, *args, **kwargs):
    if host == destination.hostname and port == destination.port:
        return await httpcore.AnyIOBackend.connect_tcp(
            self, "127.0.0.1", port, *args, **kwargs
        )
    return await original_connect(self, host, port, *args, **kwargs)


def context(*args, **kwargs):
    value = original_context(*args, **kwargs)
    value.load_verify_locations(cafile=data["cert"])
    return value


PublicBackend.connect_tcp = connect
ssl.create_default_context = context


async def run():
    async with queue.open_async():
        await queue.run_worker_async(
            fetch_job_polling_interval=0.1, abort_job_polling_interval=0.05
        )


asyncio.run(run())
