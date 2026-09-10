"""No database: real local journal durability and controlled retention clock."""
import io
import os
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event

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


def test_empty_or_interrupted_backup_is_never_published(ledger):
    assert not ledger.exists()
    journal.initialize()
    with pytest.raises(ValueError, match='空备份'):
        retention.store(io.BytesIO())
    assert not list(retention.directory().iterdir())


def test_registration_failure_removes_published_backup(ledger, monkeypatch):
    assert not ledger.exists()
    journal.initialize()
    connect = journal.connect
    calls = 0

    def registration_fails():
        nonlocal calls
        calls += 1
        if calls == 2:
            assert list(retention.directory().glob('.*.partial'))
            assert not list(retention.directory().glob('*.dump'))
            raise sqlite3.OperationalError('synthetic registration failure')
        return connect()

    monkeypatch.setattr(journal, 'connect', registration_fails)
    with pytest.raises(sqlite3.OperationalError, match='synthetic'):
        retention.store(io.BytesIO(b'complete-but-unregistered'))
    assert not list(retention.directory().iterdir())


def test_partial_directory_entry_is_synced_before_registration(ledger, monkeypatch):
    assert not ledger.exists()
    journal.initialize()
    connect = journal.connect
    calls = 0

    def counted_connect():
        nonlocal calls
        calls += 1
        return connect()

    def sync_fails(_path):
        raise OSError('synthetic partial directory fsync failure')

    monkeypatch.setattr(journal, 'connect', counted_connect)
    monkeypatch.setattr(retention, '_sync_directory', sync_fails)
    with pytest.raises(OSError, match='synthetic'):
        retention.store(io.BytesIO(b'complete-but-not-directory-durable'))
    assert calls == 1
    with connect() as connection:
        assert connection.execute('SELECT count(*) FROM backup').fetchone()[0] == 0
    assert not list(retention.directory().iterdir())


def test_store_and_expire_serialize_without_touching_live_partial(ledger):
    assert not ledger.exists()
    journal.initialize()
    entered, release = Event(), Event()

    class BlockingStream(io.BytesIO):
        def read(self, size=-1):
            entered.set()
            assert release.wait(5)
            return super().read(size)

    with ThreadPoolExecutor(max_workers=2) as pool:
        stored = pool.submit(retention.store, BlockingStream(b'concurrent-backup'))
        assert entered.wait(5)
        expired = pool.submit(retention.expire)
        assert not expired.done()
        release.set()
        identity = stored.result(timeout=5)
        assert expired.result(timeout=5) == 0
    assert (retention.directory() / f'{identity}.dump').is_file()


def test_sigkill_partial_recovery_on_each_commit_side(ledger):
    assert not ledger.exists()
    journal.initialize()
    root = retention.directory()
    root.mkdir()
    now = datetime.now(UTC)

    before_commit = root / f'.{uuid.uuid4()}.partial'
    before_commit.write_bytes(b'interrupted-before-journal-commit')
    assert retention.expire(now) == 0
    assert before_commit.exists()
    old = (now - retention.PARTIAL_RECOVERY_AFTER).timestamp()
    os.utime(before_commit, (old, old))
    assert retention.expire(now) == 0
    assert not before_commit.exists()

    after_commit = uuid.uuid4()
    pending = root / f'.{after_commit}.partial'
    pending.write_bytes(b'fsynced-before-rename')
    with journal.connect() as connection:
        with connection:
            connection.execute(
                'INSERT INTO backup VALUES (?,?)', (str(after_commit), now.isoformat())
            )
    assert retention.expire(now) == 0
    assert not pending.exists()
    assert (root / f'{after_commit}.dump').read_bytes() == b'fsynced-before-rename'


def test_rename_failure_withdraws_registration_and_partial(ledger, monkeypatch):
    assert not ledger.exists()
    journal.initialize()
    replace = Path.replace

    def rename_fails(path, target):
        if path.name.endswith('.partial'):
            raise OSError('synthetic rename failure')
        return replace(path, target)

    monkeypatch.setattr(Path, 'replace', rename_fails)
    with pytest.raises(OSError, match='synthetic'):
        retention.store(io.BytesIO(b'complete-before-rename'))
    with journal.connect() as connection:
        assert connection.execute('SELECT count(*) FROM backup').fetchone()[0] == 0
    assert not list(retention.directory().iterdir())


def test_directory_fsync_failure_after_rename_keeps_registered_final(
    ledger, monkeypatch
):
    assert not ledger.exists()
    journal.initialize()

    sync = retention._sync_directory
    calls = 0

    def second_sync_fails(path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError('synthetic directory fsync failure')
        sync(path)

    monkeypatch.setattr(retention, '_sync_directory', second_sync_fails)
    with pytest.raises(OSError, match='synthetic'):
        retention.store(io.BytesIO(b'committed-and-renamed'))
    files = list(retention.directory().glob('*.dump'))
    assert len(files) == 1 and files[0].read_bytes() == b'committed-and-renamed'
    assert not list(retention.directory().glob('.*.partial'))
    with journal.connect() as connection:
        rows = connection.execute('SELECT id FROM backup').fetchall()
    assert rows == [(files[0].stem,)]
    assert retention.expire() == 0


def test_expire_recovers_registered_tombstone_after_rename_fsync_failure(
    ledger, monkeypatch
):
    assert not ledger.exists()
    journal.initialize()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    stored = retention.store(io.BytesIO(b'expired'), now)
    sync = retention._sync_directory

    def sync_fails(_path):
        raise OSError('synthetic tombstone directory fsync failure')

    monkeypatch.setattr(retention, '_sync_directory', sync_fails)
    with pytest.raises(OSError, match='synthetic'):
        retention.expire(now + timedelta(days=30))
    root = retention.directory()
    assert not (root / f'{stored}.dump').exists()
    assert (root / f'.{stored}.deleting').read_bytes() == b'expired'
    with journal.connect() as connection:
        assert connection.execute('SELECT id FROM backup').fetchall() == [
            (str(stored),)
        ]
    monkeypatch.setattr(retention, '_sync_directory', sync)
    assert retention.expire(now + timedelta(days=30)) == 0
    assert not list(root.iterdir())


def test_expire_recovers_registered_tombstone_after_row_delete_failure(ledger):
    assert not ledger.exists()
    journal.initialize()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    stored = retention.store(io.BytesIO(b'expired'), now)
    with journal.connect() as connection:
        connection.execute(
            "CREATE TRIGGER backup_delete_fails BEFORE DELETE ON backup "
            "BEGIN SELECT RAISE(ABORT, 'synthetic row delete failure'); END"
        )
        connection.commit()
    with pytest.raises(sqlite3.IntegrityError, match='synthetic'):
        retention.expire(now + timedelta(days=30))
    tombstone = retention.directory() / f'.{stored}.deleting'
    assert tombstone.read_bytes() == b'expired'
    with journal.connect() as connection:
        assert connection.execute('SELECT id FROM backup').fetchall() == [
            (str(stored),)
        ]
        connection.execute('DROP TRIGGER backup_delete_fails')
        connection.commit()
    assert retention.expire(now + timedelta(days=30)) == 0
    assert not list(retention.directory().iterdir())


def test_expire_removes_unregistered_tombstone_after_unlink_failure(
    ledger, monkeypatch
):
    assert not ledger.exists()
    journal.initialize()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    stored = retention.store(io.BytesIO(b'expired'), now)
    unlink = Path.unlink

    def tombstone_unlink_fails(path, *args, **kwargs):
        if path.name.endswith('.deleting'):
            raise OSError('synthetic tombstone unlink failure')
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'unlink', tombstone_unlink_fails)
    with pytest.raises(OSError, match='synthetic'):
        retention.expire(now + timedelta(days=30))
    tombstone = retention.directory() / f'.{stored}.deleting'
    assert tombstone.read_bytes() == b'expired'
    with journal.connect() as connection:
        assert connection.execute('SELECT id FROM backup').fetchall() == []
    monkeypatch.setattr(Path, 'unlink', unlink)
    assert retention.expire(now + timedelta(days=30)) == 0
    assert not list(retention.directory().iterdir())


def test_expire_is_reconciled_after_tombstone_unlink_fsync_failure(
    ledger, monkeypatch
):
    assert not ledger.exists()
    journal.initialize()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    retention.store(io.BytesIO(b'expired'), now)
    sync = retention._sync_directory
    calls = 0

    def second_sync_fails(path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError('synthetic post-unlink fsync failure')
        sync(path)

    monkeypatch.setattr(retention, '_sync_directory', second_sync_fails)
    with pytest.raises(OSError, match='synthetic'):
        retention.expire(now + timedelta(days=30))
    assert not list(retention.directory().iterdir())
    with journal.connect() as connection:
        assert connection.execute('SELECT id FROM backup').fetchall() == []
    monkeypatch.setattr(retention, '_sync_directory', sync)
    assert retention.expire(now + timedelta(days=30)) == 0


def test_unknown_backup_file_cannot_be_claimed_expired_or_silently_removed(ledger):
    assert not ledger.exists()
    journal.initialize()
    retention.directory().mkdir()
    unknown = retention.directory() / f'{uuid.uuid4()}.dump'
    unknown.write_bytes(b'synthetic')
    with pytest.raises(RuntimeError, match='未登记'):
        retention.expire()
    assert unknown.read_bytes() == b'synthetic'
