"""The SQLite journal lives outside PostgreSQL backups; runtime never creates it."""

import os
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

from app.core.config import settings


class Entry(NamedTuple):
    sequence: int
    user_id: uuid.UUID
    request_id: uuid.UUID
    accepted_at: datetime


def path() -> Path:
    return Path(settings.ACCOUNT_ERASURE_JOURNAL).absolute()


def initialize() -> str:
    location = path()
    location.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(location, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    identity = str(uuid.uuid4())
    with closing(sqlite3.connect(location)) as connection:
        connection.executescript("""
            CREATE TABLE identity (id TEXT PRIMARY KEY);
            CREATE TABLE backup (id TEXT PRIMARY KEY, created_at TEXT NOT NULL);
            CREATE TABLE deletion (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT UNIQUE NOT NULL,
                request_id TEXT UNIQUE NOT NULL,
                accepted_at TEXT NOT NULL
            );
            CREATE TRIGGER no_delete BEFORE DELETE ON deletion
                BEGIN SELECT RAISE(ABORT, 'deletion journal is append-only'); END;
            CREATE TRIGGER no_update BEFORE UPDATE ON deletion
                BEGIN SELECT RAISE(ABORT, 'deletion journal is append-only'); END;
        """)
        connection.execute("INSERT INTO identity VALUES (?)", (identity,))
        connection.commit()
    return identity


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    location = path()
    if location.is_symlink() or location.stat().st_mode & 0o077:
        raise RuntimeError("独立删除日志必须是权限 0600 的普通文件")
    # mode=rw is essential: a missing journal is an outage, never a new empty history.
    connection = sqlite3.connect(location.as_uri() + "?mode=rw", uri=True, timeout=10)
    try:
        connection.execute("PRAGMA synchronous=FULL")
        yield connection
    finally:
        connection.close()


def read() -> tuple[str, list[Entry]]:
    with connect() as connection:
        identity = connection.execute("SELECT id FROM identity").fetchone()
        if identity is None:
            raise RuntimeError("独立删除日志缺少身份；禁止自动初始化")
        rows = connection.execute(
            "SELECT sequence,user_id,request_id,accepted_at FROM deletion ORDER BY sequence"
        ).fetchall()
        return identity[0], [
            Entry(n, uuid.UUID(u), uuid.UUID(r), datetime.fromisoformat(t))
            for n, u, r, t in rows
        ]


def append(user_id: uuid.UUID, request_id: uuid.UUID, accepted_at: datetime) -> Entry:
    with connect() as connection:
        with connection:
            connection.execute(
                "INSERT INTO deletion(user_id,request_id,accepted_at) VALUES (?,?,?) "
                "ON CONFLICT(user_id) DO NOTHING",
                (str(user_id), str(request_id), accepted_at.astimezone(UTC).isoformat()),
            )
        row = connection.execute(
            "SELECT sequence,user_id,request_id,accepted_at FROM deletion WHERE user_id=?",
            (str(user_id),),
        ).fetchone()
        assert row
        if row[2] != str(request_id):
            raise ValueError("该账号已有另一项不可撤销的注销决定")
        return Entry(row[0], user_id, request_id, datetime.fromisoformat(row[3]))


def contains(user_id: uuid.UUID) -> bool:
    with connect() as connection:
        return connection.execute(
            "SELECT 1 FROM deletion WHERE user_id=?", (str(user_id),)
        ).fetchone() is not None


def head() -> tuple[str, int]:
    with connect() as connection:
        row = connection.execute("SELECT id,(SELECT coalesce(max(sequence),0) FROM deletion) FROM identity").fetchone()
        if row is None:
            raise RuntimeError("独立删除日志缺少身份")
        return row[0], row[1]
