"""Short, read-only snapshots for multi-query public training projections."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlmodel import Session

from app.core.db import engine


@contextmanager
def read_snapshot() -> Iterator[Session]:
    # Never borrow the request transaction: callers may hold a mutation lock.
    # A fresh identity map and one MVCC snapshot keep related committed facts
    # together without waiting for the User lock held during a remote call.
    with (
        engine.connect().execution_options(
            isolation_level="REPEATABLE READ", postgresql_readonly=True
        ) as connection,
        Session(connection) as session,
    ):
        yield session
