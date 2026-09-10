import json
import logging
import os
from datetime import UTC, datetime, timedelta

import pytest

from app.operations import admin, maintenance, state


def test_managed_state_missing_corrupt_and_pending_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("OPERATIONS_ROOT", str(tmp_path))
    with pytest.raises(FileNotFoundError):
        state.require_open()
    (tmp_path / "restore.json").write_text("{")
    with pytest.raises(json.JSONDecodeError):
        state.require_open()
    state.publish("restoring")
    with pytest.raises(RuntimeError):
        state.require_open()
    assert state.phase() == "restoring"
    state.publish("ready")
    state.require_open()
    assert state.phase() == "ready"
    assert (tmp_path / "restore.json").stat().st_mode & 0o777 == 0o600


def test_restore_terminalizes_every_persisted_incomplete_state():
    assert len(admin.ACTIVE) == 7
    assert "needs_supplement" in admin.ACTIVE["training_submission"]
    assert "needs_clarification" in admin.ACTIVE["training_evaluation"]


def test_expiration_only_dedicated_unreferenced_files_at_boundary(tmp_path):
    now = datetime.now(UTC)
    cache = tmp_path / "unreferenced-cache"
    cache.mkdir()
    for name, age in [
        ("expired", timedelta(days=7)),
        ("live", timedelta(days=7, seconds=-1)),
    ]:
        path = cache / name
        path.write_text("synthetic temporary only")
        stamp = (now - age).timestamp()
        os.utime(path, (stamp, stamp))
    private = tmp_path / "active-draft"
    private.write_text("kept regardless of absence")
    assert maintenance.clean(cache, 7, now) == 1
    assert sorted(p.name for p in cache.iterdir()) == ["live"]
    assert private.read_text() == "kept regardless of absence"
    (cache / "link").symlink_to(private)
    with pytest.raises(RuntimeError):
        maintenance.clean(cache, 7, now)
    assert private.exists()


def test_log_never_serializes_message_arguments_or_exception(tmp_path, monkeypatch):
    monkeypatch.setenv("OPERATIONS_ROOT", str(tmp_path))
    handler = maintenance.SafeLog()
    secret = "synthetic-api-key-password-source-prompt"
    record = logging.LogRecord(
        "unsafe", logging.ERROR, "file", 1, secret, (secret,), None
    )
    record.exc_text = secret
    handler.emit(record)
    payload = "".join(p.read_text() for p in (tmp_path / "logs").iterdir())
    assert "ERROR" in payload and secret not in payload
