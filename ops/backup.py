"""Create and validate one registered dump with fixed Compose services."""

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".private/runtime.env"
TRANSIENT = ROOT / ".private/state/unreferenced-cache"
COMPOSE = [
    "docker",
    "compose",
    "-p",
    "bp-issue-33",
    "--env-file",
    str(ENV),
    "-f",
    str(ROOT / "compose.yml"),
    "-f",
    str(ROOT / "ops/compose.yml"),
]


def main() -> None:
    if not ENV.is_file() or TRANSIENT.is_symlink():
        raise RuntimeError("须先准备独立运行环境")
    TRANSIENT.mkdir(mode=0o700, parents=True, exist_ok=True)
    database = dict(
        line.split("=", 1) for line in ENV.read_text().splitlines() if line
    ).get("APP_DATABASE", "bp")
    descriptor, name = tempfile.mkstemp(
        prefix="backup-", suffix=".partial", dir=TRANSIENT
    )
    location = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            subprocess.run(
                COMPOSE
                + [
                    "exec",
                    "-T",
                    "db",
                    "pg_dump",
                    "-U",
                    "bp",
                    "-d",
                    database,
                    "-Fc",
                ],
                stdout=output,
                check=True,
            )
        if not location.stat().st_size:
            raise RuntimeError("数据库未生成备份")
        with location.open("rb") as source:
            subprocess.run(
                COMPOSE + ["exec", "-T", "db", "pg_restore", "--list"],
                stdin=source,
                stdout=subprocess.DEVNULL,
                check=True,
            )
        with location.open("rb") as source:
            subprocess.run(
                COMPOSE + ["run", "--rm", "-T", "operator", "store-backup"],
                stdin=source,
                check=True,
            )
    finally:
        location.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from None
