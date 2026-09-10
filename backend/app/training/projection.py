"""Short, read-only snapshots ordered against permanent content erasure."""

import hashlib
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlmodel import Session

from app.core.db import engine


@contextmanager
def read_snapshot(user_id: uuid.UUID | None = None) -> Iterator[Session]:
    # Never borrow the request transaction: callers may hold a mutation lock.
    # Take a session advisory lock BEFORE starting RR. A lock statement inside
    # RR would fix the snapshot before any wait, exposing pre-erasure content.
    # One checkout, same as the original projection: no guard connection occupies
    # the shared pool while waiting for a second connection. No reader takes User.
    with engine.connect() as connection:
        locked = False
        key = erasure_lock_key(user_id) if user_id is not None else None
        try:
            if key is not None:
                connection.execution_options(isolation_level="AUTOCOMMIT")
                connection.execute(
                    text("SELECT pg_advisory_lock_shared(:key)"), {"key": key}
                )
                locked = True
                connection.rollback()  # End SQLAlchemy's autocommit bookkeeping.
            connection.execution_options(
                isolation_level="REPEATABLE READ", postgresql_readonly=True
            )
            with Session(connection) as session:
                if user_id is not None:
                    from app.account_erasure.service import require_account

                    require_account(user_id)
                yield session
        finally:
            if locked:
                try:
                    connection.rollback()
                    connection.execution_options(
                        isolation_level="AUTOCOMMIT", postgresql_readonly=False
                    )
                    released = connection.execute(
                        text("SELECT pg_advisory_unlock_shared(:key)"), {"key": key}
                    ).scalar_one()
                    if not released:
                        raise RuntimeError("erasure read lock was not held")
                except BaseException:
                    # A session-level lock must never be returned to the pool.
                    # Closing the physical connection releases it on any failure.
                    connection.invalidate()
                    raise


def erasure_lock_key(user_id: uuid.UUID) -> int:
    return int.from_bytes(
        hashlib.sha256(b"learning-erasure:" + user_id.bytes).digest()[:8],
        "big",
        signed=True,
    )
