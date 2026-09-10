"""Bounded local backup store for controlled drills; no production scheduler claim."""

import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import BinaryIO

from app.account_erasure import journal


def directory() -> Path:
    return journal.path().parent / "backups"


def store(stream: BinaryIO, now: datetime | None = None) -> uuid.UUID:
    """Copy an operator-provided PostgreSQL dump, never the independent journal."""
    identity = uuid.uuid4()
    instant = now or datetime.now(UTC)
    root = directory()
    if root.is_symlink():
        raise RuntimeError("备份目录不能是符号链接")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    location = root / f"{identity}.dump"
    pending = root / f".{identity}.partial"
    try:
        with os.fdopen(
            os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
        ) as target:
            size = 0
            while chunk := stream.read(65536):
                size += target.write(chunk)
            if not size:
                raise ValueError("拒绝登记空备份")
            target.flush()
            os.fsync(target.fileno())
        pending.replace(location)
        descriptor = os.open(root, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        pending.unlink(missing_ok=True)
    with journal.connect() as connection:
        with connection:
            connection.execute(
                "INSERT INTO backup VALUES (?,?)",
                (str(identity), instant.astimezone(UTC).isoformat()),
            )
    return identity


def expire(now: datetime | None = None) -> int:
    instant = now or datetime.now(UTC)
    root = directory()
    if root.is_symlink():
        raise RuntimeError("备份目录不能是符号链接")
    removed = 0
    with journal.connect() as connection:
        rows = connection.execute("SELECT id,created_at FROM backup").fetchall()
        known = {f"{uuid.UUID(identity)}.dump" for identity, _ in rows}
        if root.exists() and any(p.name not in known for p in root.iterdir()):
            raise RuntimeError("备份目录存在未登记文件；须核对后再声明保留期合规")
        for identity, created in rows:
            if datetime.fromisoformat(created) + timedelta(days=30) > instant:
                continue
            path = root / f"{uuid.UUID(identity)}.dump"
            if path.is_symlink():
                raise RuntimeError("备份文件不能是符号链接")
            path.unlink(missing_ok=True)
            with connection:
                connection.execute("DELETE FROM backup WHERE id=?", (identity,))
            removed += 1
    return removed
