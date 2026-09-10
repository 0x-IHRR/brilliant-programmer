"""No database: real local journal durability and controlled retention clock."""
import io
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from app.account_erasure import journal, retention
from app.core.config import settings


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    location = tmp_path / 'independent' / 'deletions.sqlite3'
    monkeypatch.setattr(settings, 'ACCOUNT_ERASURE_JOURNAL', str(location))
    return location


def test_missing_journal_is_not_fresh_install(ledger):
    with pytest.raises(FileNotFoundError):
        journal.head()
    assert not ledger.exists()
    identity = journal.initialize()
    assert journal.head() == (identity, 0)
    assert ledger.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        journal.initialize()
    ledger.chmod(0o644)
    with pytest.raises(RuntimeError, match='0600'):
        journal.head()


def test_concurrent_same_request_has_one_append_only_identity(ledger):
    assert not ledger.exists()
    identity = journal.initialize()
    owner, request = uuid.uuid4(), uuid.uuid4()
    now = datetime.now(UTC)
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda _: journal.append(owner, request, now), range(8)))
    assert all(row == rows[0] for row in rows)
    assert journal.read() == (identity, [rows[0]])
    assert journal.contains(owner)
    assert not journal.contains(uuid.uuid4())
    with pytest.raises(ValueError):
        journal.append(owner, uuid.uuid4(), now)
    with journal.connect() as connection:
        with pytest.raises(sqlite3.IntegrityError, match='append-only'):
            connection.execute('DELETE FROM deletion')
        with pytest.raises(sqlite3.IntegrityError, match='append-only'):
            connection.execute("UPDATE deletion SET accepted_at='later'")
    assert journal.read() == (identity, [rows[0]])


def test_backup_bytes_expire_at_thirty_days_without_erasing_journal(ledger):
    assert not ledger.exists()
    identity = journal.initialize()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    entry = journal.append(uuid.uuid4(), uuid.uuid4(), now)
    stored = retention.store(io.BytesIO(b'synthetic-private-backup'), now)
    file = retention.directory() / f'{stored}.dump'
    assert file.read_bytes() == b'synthetic-private-backup'
    assert file.stat().st_mode & 0o777 == 0o600
    assert retention.expire(now + timedelta(days=30, microseconds=-1)) == 0
    assert file.exists()
    assert retention.expire(now + timedelta(days=30)) == 1
    assert not file.exists()
    assert retention.expire(now + timedelta(days=31)) == 0
    assert journal.read() == (identity, [entry])


def test_unknown_backup_file_cannot_be_claimed_expired_or_silently_removed(ledger):
    assert not ledger.exists()
    journal.initialize()
    retention.directory().mkdir()
    unknown = retention.directory() / 'unregistered.dump'
    unknown.write_bytes(b'synthetic')
    with pytest.raises(RuntimeError, match='未登记'):
        retention.expire()
    assert unknown.read_bytes() == b'synthetic'
