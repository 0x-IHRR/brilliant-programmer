import importlib.util
import json
import logging
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.operations import admin, maintenance, state


def operations_module(name):
    path = Path(__file__).parents[2] / "ops" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"operations_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backup = operations_module("backup")
measure = operations_module("measure")
prepare = operations_module("prepare")


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
    assert len(admin.RESTORE_INCOMPLETE) == 7
    assert "needs_supplement" in admin.RESTORE_INCOMPLETE["training_submission"]
    assert "needs_clarification" in admin.RESTORE_INCOMPLETE["training_evaluation"]


@pytest.mark.parametrize("identity", ("uid", "gid"))
def test_prepare_rejects_root_container_identity(tmp_path, monkeypatch, identity):
    monkeypatch.setattr(prepare, "PRIVATE", tmp_path / "private")
    monkeypatch.setattr(os, "getuid", lambda: 0 if identity == "uid" else 1000)
    monkeypatch.setattr(os, "getgid", lambda: 0 if identity == "gid" else 1000)
    with pytest.raises(RuntimeError, match="root"):
        prepare.prepare()
    assert not prepare.PRIVATE.exists()


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


def test_backup_propagates_dump_and_validation_failures(tmp_path, monkeypatch):
    environment = tmp_path / "runtime.env"
    environment.write_text("APP_DATABASE=isolated\n")
    transient = tmp_path / "unreferenced-cache"
    monkeypatch.setattr(backup, "ENV", environment)
    monkeypatch.setattr(backup, "TRANSIENT", transient)

    calls = []

    def dump_fails(arguments, **_kwargs):
        calls.append(arguments)
        raise subprocess.CalledProcessError(2, arguments)

    monkeypatch.setattr(subprocess, "run", dump_fails)
    with pytest.raises(subprocess.CalledProcessError):
        backup.main()
    assert len(calls) == 1 and "pg_dump" in calls[0]
    assert not list(transient.iterdir())
    calls.clear()

    def validation_fails(arguments, **kwargs):
        calls.append(arguments)
        if len(calls) == 1:
            kwargs["stdout"].write(b"synthetic-dump")
            return subprocess.CompletedProcess(arguments, 0)
        raise subprocess.CalledProcessError(1, arguments)

    monkeypatch.setattr(subprocess, "run", validation_fails)
    with pytest.raises(subprocess.CalledProcessError):
        backup.main()
    assert len(calls) == 2 and "pg_restore" in calls[1]
    assert not any("store-backup" in command for command in calls)
    assert not list(transient.iterdir())


def test_measurement_uses_true_even_sample_median():
    assert measure.summary([1.0, 2.0, 3.0, 100.0])["median_ms"] == 2.5
