"""Bounded local backup store for controlled drills; no production scheduler claim."""

import fcntl
import os
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import BinaryIO

from app.account_erasure import journal

PARTIAL_RECOVERY_AFTER = timedelta(days=1)


def directory() -> Path:
    return journal.path().parent / "backups"


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _partial_identity(path: Path) -> uuid.UUID | None:
    if not path.name.startswith(".") or not path.name.endswith(".partial"):
        return None
    value = path.name[1:-8]
    try:
        identity = uuid.UUID(value)
    except ValueError:
        return None
    return identity if value == str(identity) else None


def _tombstone_identity(path: Path) -> uuid.UUID | None:
    if not path.name.startswith(".") or not path.name.endswith(".deleting"):
        return None
    value = path.name[1:-9]
    try:
        identity = uuid.UUID(value)
    except ValueError:
        return None
    return identity if value == str(identity) else None


@contextmanager
def _locked(root: Path) -> Iterator[None]:
    lock = root.parent / ".backups.lock"
    descriptor = os.open(
        lock, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600
    )
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _reconcile(
    root: Path, connection: sqlite3.Connection, instant: datetime
) -> list[tuple[str, str]]:
    rows = connection.execute("SELECT id,created_at FROM backup").fetchall()
    retained = []
    known = set()
    for raw_identity, created_at in rows:
        identity = uuid.UUID(raw_identity)
        location = root / f"{identity}.dump"
        pending = root / f".{identity}.partial"
        tombstone = root / f".{identity}.deleting"
        present = [path for path in (location, pending, tombstone) if path.exists()]
        if len(present) > 1:
            raise RuntimeError("已登记备份存在冲突的持久化状态")
        if location.exists():
            if location.is_symlink() or not location.is_file():
                raise RuntimeError("备份文件类型异常")
        elif pending.exists():
            if pending.is_symlink() or not pending.is_file():
                raise RuntimeError("备份临时文件类型异常")
            pending.replace(location)
            _sync_directory(root)
        elif tombstone.exists():
            if tombstone.is_symlink() or not tombstone.is_file():
                raise RuntimeError("备份删除标记类型异常")
            if datetime.fromisoformat(created_at) + timedelta(days=30) <= instant:
                with connection:
                    connection.execute("DELETE FROM backup WHERE id=?", (raw_identity,))
                tombstone.unlink()
                _sync_directory(root)
                continue
            tombstone.replace(location)
            _sync_directory(root)
        else:
            raise RuntimeError("已登记备份缺失；须先恢复完整字节")
        known.add(location.name)
        retained.append((raw_identity, created_at))
    for path in root.iterdir():
        if path.name in known:
            continue
        if _partial_identity(path) is not None:
            if path.is_symlink() or not path.is_file():
                raise RuntimeError("备份临时文件类型异常")
            modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
            if modified + PARTIAL_RECOVERY_AFTER <= instant:
                path.unlink()
                _sync_directory(root)
            continue
        if _tombstone_identity(path) is not None:
            if path.is_symlink() or not path.is_file():
                raise RuntimeError("备份删除标记类型异常")
            path.unlink()
            _sync_directory(root)
            continue
        raise RuntimeError("备份目录存在未登记文件；须核对后再声明保留期合规")
    return retained


def store(stream: BinaryIO, now: datetime | None = None) -> uuid.UUID:
    """Copy an operator-provided PostgreSQL dump, never the independent journal."""
    identity = uuid.uuid4()
    instant = now or datetime.now(UTC)
    root = directory()
    if root.is_symlink():
        raise RuntimeError("备份目录不能是符号链接")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with _locked(root):
        with journal.connect() as connection:
            _reconcile(root, connection, instant)
        location = root / f"{identity}.dump"
        pending = root / f".{identity}.partial"
        registered = False
        try:
            with os.fdopen(
                os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600),
                "wb",
            ) as target:
                size = 0
                while chunk := stream.read(65536):
                    size += target.write(chunk)
                if not size:
                    raise ValueError("拒绝登记空备份")
                target.flush()
                os.fsync(target.fileno())
            _sync_directory(root)
            with journal.connect() as connection:
                with connection:
                    connection.execute(
                        "INSERT INTO backup VALUES (?,?)",
                        (str(identity), instant.astimezone(UTC).isoformat()),
                    )
            registered = True
            pending.replace(location)
            _sync_directory(root)
        except BaseException:
            if location.exists():
                # Rename succeeded: keep the committed row and final for reconciliation.
                raise
            if registered:
                try:
                    with journal.connect() as connection:
                        with connection:
                            connection.execute(
                                "DELETE FROM backup WHERE id=?", (str(identity),)
                            )
                except BaseException:
                    # The committed row makes the fsynced partial recoverable.
                    raise
            if pending.exists():
                pending.unlink()
                _sync_directory(root)
            if location.exists():
                location.unlink()
                _sync_directory(root)
            raise
    return identity


def expire(now: datetime | None = None) -> int:
    instant = now or datetime.now(UTC)
    root = directory()
    if root.is_symlink():
        raise RuntimeError("备份目录不能是符号链接")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    removed = 0
    with _locked(root):
        with journal.connect() as connection:
            rows = _reconcile(root, connection, instant)
            for identity, created in rows:
                if datetime.fromisoformat(created) + timedelta(days=30) > instant:
                    continue
                path = root / f"{uuid.UUID(identity)}.dump"
                if path.is_symlink():
                    raise RuntimeError("备份文件不能是符号链接")
                tombstone = root / f".{uuid.UUID(identity)}.deleting"
                path.replace(tombstone)
                _sync_directory(root)
                with connection:
                    connection.execute("DELETE FROM backup WHERE id=?", (identity,))
                tombstone.unlink()
                _sync_directory(root)
                removed += 1
    return removed
