"""Owned transient directories only; database learning records are never aged out."""

import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.account_erasure.operations import audit_deadlines
from app.account_erasure.retention import expire
from app.operations.state import require_open, root


def clean(directory: Path, days: int, now: datetime) -> int:
    if directory.is_symlink():
        raise RuntimeError("留存目录不能为符号链接")
    directory.mkdir(mode=0o700, exist_ok=True)
    count = 0
    for path in directory.iterdir():
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("留存目录出现未支持的对象，须核实后继续")
        if datetime.fromtimestamp(path.stat().st_mtime, UTC) <= now - timedelta(
            days=days
        ):
            path.unlink()
            count += 1
    return count


def run(now: datetime | None = None) -> dict[str, int]:
    require_open()
    directory = root()
    if directory is None:
        raise RuntimeError("未配置托管留存目录")
    instant = now or datetime.now(UTC)
    result = {
        "cache": clean(directory / "unreferenced-cache", 7, instant),
        "logs": clean(directory / "logs", 30, instant),
        "backups": expire(instant),
    }
    audit_deadlines(instant)
    return result


async def loop() -> None:
    while True:
        # ponytail: one serial maintenance pass per minute; no second scheduler.
        # Its owned cache contains no referenced sources or active drafts.
        await asyncio.to_thread(run)
        directory = root()
        assert directory
        (directory / "maintenance.heartbeat").touch()
        await asyncio.sleep(60)


class SafeLog(logging.Handler):
    """Deliberately omit messages/tracebacks/arguments: they may contain private input."""

    def emit(self, record: logging.LogRecord) -> None:
        directory = root()
        if directory is None:
            return
        logs = directory / "logs"
        if logs.is_symlink():
            raise RuntimeError("日志目录不能为符号链接")
        logs.mkdir(mode=0o700, exist_ok=True)
        now = datetime.now(UTC)
        path = logs / f"{now:%Y-%m-%d}.log"
        descriptor = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(descriptor, "w") as output:
            output.write(f"{now.isoformat()} {record.levelname}\n")


def logging_setup() -> None:
    handler = SafeLog()
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "procrastinate"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
