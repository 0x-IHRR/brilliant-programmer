"""An explicitly configured managed installation never defaults missing state open."""

import json
import os
import uuid
from pathlib import Path


def root() -> Path | None:
    configured = os.environ.get("OPERATIONS_ROOT")
    return Path(configured) if configured else None


def require_open() -> None:
    directory = root()
    if directory is None:
        return
    path = directory / "restore.json"
    if directory.is_symlink() or path.is_symlink():
        raise RuntimeError("恢复状态路径不能为符号链接")
    value = json.loads(path.read_text())
    if value != {"phase": "ready"}:
        raise RuntimeError("恢复未完成，应用和任务保持隔离")


def phase() -> str:
    directory = root()
    if directory is None:
        raise RuntimeError("须配置独立托管状态目录")
    path = directory / "restore.json"
    if directory.is_symlink() or path.is_symlink():
        raise RuntimeError("恢复状态路径不能为符号链接")
    value = json.loads(path.read_text())
    if value not in ({"phase": "ready"}, {"phase": "restoring"}):
        raise RuntimeError("未知恢复阶段")
    return str(value["phase"])


def publish(phase: str) -> None:
    if phase not in {"ready", "restoring"}:
        raise ValueError("未知恢复阶段")
    directory = root()
    if directory is None or directory.is_symlink():
        raise RuntimeError("须配置独立托管状态目录")
    path = directory / "restore.json"
    if path.is_symlink():
        raise RuntimeError("恢复状态不能为符号链接")
    pending = directory / (".restore-" + uuid.uuid4().hex)
    try:
        with os.fdopen(
            os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
        ) as out:
            json.dump({"phase": phase}, out)
            out.flush()
            os.fsync(out.fileno())
        pending.replace(path)
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        pending.unlink(missing_ok=True)
