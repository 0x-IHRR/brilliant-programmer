"""Reproduce bounded parser, HTTPS, resource, and failure-exit measurements."""

from __future__ import annotations

import json
import math
import os
import ssl
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".private/runtime.env"
TLS = ROOT / ".private/tls/cert.pem"
BASE = "https://localhost:18443"


def environment() -> dict[str, str]:
    values = dict(line.split("=", 1) for line in ENV.read_text().splitlines() if line)
    return (
        os.environ
        | values
        | {
            "DATABASE_URL": (
                f"postgresql://bp:{values['POSTGRES_PASSWORD']}@127.0.0.1:"
                f"{values['DB_PORT']}/{values['APP_DATABASE']}"
            ),
            "ACCOUNT_ERASURE_JOURNAL": str(
                ROOT / ".private/state/account-deletions.sqlite3"
            ),
            "OPERATIONS_ROOT": str(ROOT / ".private/state"),
            "MAILPIT_URL": f"http://127.0.0.1:{values['MAILPIT_HTTP_PORT']}",
            "NO_PROXY": "localhost,127.0.0.1",
        }
    )


def request(
    path: str,
    context: ssl.SSLContext,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    method: str | None = None,
) -> bytes:
    target = urllib.request.Request(
        BASE + path, data=data, headers=headers or {}, method=method
    )
    with urllib.request.urlopen(target, context=context, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"unexpected status {response.status} for {path}")
        return cast(bytes, response.read())


def timed(callable_: Callable[[], object], count: int) -> list[float]:
    samples = []
    for _ in range(count):
        started = time.perf_counter()
        callable_()
        samples.append((time.perf_counter() - started) * 1000)
    return samples


def summary(samples: list[float]) -> dict[str, float | int]:
    ordered = sorted(samples)
    return {
        "samples": len(samples),
        "median_ms": round(ordered[len(ordered) // 2], 2),
        "p95_ms": round(ordered[math.ceil(len(ordered) * 0.95) - 1], 2),
        "max_ms": round(ordered[-1], 2),
    }


def main() -> None:
    if not ENV.is_file() or not TLS.is_file():
        raise RuntimeError("须先准备并启动独立 Compose 环境")
    artifact = Path(tempfile.mkdtemp(prefix="bp-issue-33-measure-", dir="/tmp"))
    child_env = environment()
    parser_log = artifact / "project-sources.log"
    started = time.perf_counter()
    with parser_log.open("wb") as output:
        parsed = subprocess.run(
            [
                "uv",
                "run",
                "--directory",
                str(ROOT / "backend"),
                "python",
                "-m",
                "pytest",
                "tests/test_project_sources.py",
                "-q",
                f"--basetemp={artifact / 'pytest'}",
            ],
            cwd=ROOT / "backend",
            env=child_env,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
    parser_seconds = round(time.perf_counter() - started, 2)
    if parsed.returncode:
        raise RuntimeError(f"解析边界失败，见 {parser_log}")

    context = ssl.create_default_context(cafile=str(TLS))
    pages = timed(lambda: request("/", context), 20)
    with ThreadPoolExecutor(max_workers=8) as pool:
        health = list(
            pool.map(
                lambda _: timed(lambda: request("/health", context), 1)[0],
                range(32),
            )
        )

    values = dict(line.split("=", 1) for line in ENV.read_text().splitlines() if line)

    def login_save() -> None:
        form = urllib.parse.urlencode(
            {
                "username": values["FIRST_SUPERUSER"],
                "password": values["FIRST_SUPERUSER_PASSWORD"],
            }
        ).encode()
        token = json.loads(
            request(
                "/api/v1/login/access-token",
                context,
                data=form,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        )["access_token"]
        if not token:
            raise RuntimeError("登录事务未保存会话")

    saves = timed(login_save, 3)
    stats = subprocess.run(
        [
            "docker",
            "stats",
            "--no-stream",
            "--format",
            "{{json .}}",
            *[f"bp-issue-33-{name}-1" for name in ("app", "worker", "db", "mail")],
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    resources = [
        {key: row[key] for key in ("Name", "CPUPerc", "MemUsage")}
        for line in stats.stdout.splitlines()
        if (row := json.loads(line))
    ]
    conflict = subprocess.run(
        ["python3", "ops/prepare.py", "ports"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if conflict.returncode == 0 or not all(
        str(port) in conflict.stderr for port in (16392, 11505, 18405, 18138, 18443)
    ):
        raise RuntimeError("端口冲突失败出口未准确触发")

    result = {
        "artifact": str(artifact),
        "parser": {
            "tests": 30,
            "wall_seconds": parser_seconds,
            "log": str(parser_log),
        },
        "https": {
            "page": summary(pages),
            "health_concurrency_8": summary(health),
            "login_save": summary(saves),
        },
        "containers": resources,
        "port_conflict_exit": conflict.returncode,
    }
    (artifact / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True))
    print(json.dumps(result, indent=2, sort_keys=True))  # noqa: T201


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from None
