"""Trusted CLI only. Restore runs while application and worker are stopped."""

import argparse
import sys

from pydantic import SecretStr
from sqlalchemy import text
from sqlmodel import Session, select

from app.account_erasure import journal
from app.account_erasure.models import JournalState
from app.account_erasure.operations import initialize, replay
from app.account_erasure.retention import store
from app.core.config import settings
from app.core.db import engine
from app.model_config.models import ModelConfig
from app.model_config.service import decrypt, encrypt
from app.models import User
from app.operations import state

ACTIVE = {
    "training_run": ("queued", "running", "stopping"),
    "project_run": ("queued", "running", "stopping"),
    "topic_job": ("queued", "running", "stopping"),
    "training_submission": ("checking", "stopping", "needs_supplement"),
    "training_evaluation": ("checking", "stopping", "needs_clarification"),
    "score_review": ("queued", "running", "stopping"),
    "concept_help": ("checking", "stopping"),
}


def initialize_managed() -> None:
    directory = state.root()
    if directory is None:
        raise RuntimeError("未指定独立托管目录")
    # First initialization never guesses that a database restored from elsewhere is new.
    if not journal.path().exists():
        initialize()
    else:
        identity, _ = journal.read()
        with Session(engine) as session:
            bound = session.get(JournalState, 1)
            if not bound or bound.identity != identity:
                raise RuntimeError("既有独立日志不能用于自动初始化旧库")
    replay(allow_restore=True)
    from app.initial_data import init

    init()
    state.publish("ready")


def quarantine_restored() -> None:
    directory = state.root()
    if directory is None or state.phase() != "restoring":
        raise RuntimeError("仅隔离中的显式恢复可撤销旧许可")
    replay(allow_restore=True)
    with Session(engine) as session:
        for config in session.exec(select(ModelConfig).with_for_update()).all():
            config.revoked = True
            session.add(config)
        for table, statuses in ACTIVE.items():
            session.execute(
                text(
                    f"UPDATE \"{table}\" SET stop_requested=true,status='stopped',"
                    "code='configuration_revoked',message=:message "
                    "WHERE status=ANY(CAST(:statuses AS text[]))"
                ),
                {
                    "message": "旧备份已恢复，未完任务不自动重派；成果与已知用量保留，请重新保存配置并主动开始。",
                    "statuses": list(statuses),
                },
            )
        # No recovered queue job may replay before its matching business terminal.
        # All existing task arguments are UUIDs; completed history stays unchanged.
        session.execute(
            text(
                "UPDATE procrastinate_jobs SET status='cancelled' WHERE status IN ('todo','doing')"
            )
        )
        session.commit()
    state.publish("ready")


def rotate_keys() -> int:
    """Re-encrypt every saved credential under the configured active key."""
    state.require_open()
    with Session(engine) as session:
        owners = sorted(session.exec(select(ModelConfig.user_id)).all(), key=str)
        for owner in owners:
            session.exec(select(User).where(User.id == owner).with_for_update()).one()
            config = session.exec(
                select(ModelConfig)
                .where(ModelConfig.user_id == owner)
                .with_for_update()
            ).one()
            plaintext: SecretStr = decrypt(config)
            config.key_version = settings.MODEL_ACTIVE_KEY_VERSION
            config.encrypted_key = encrypt(config, plaintext)
            session.add(config)
        session.commit()
    return len(owners)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=[
            "check",
            "initialize",
            "isolate",
            "finish-restore",
            "rotate-keys",
            "store-backup",
        ],
    )
    command = parser.parse_args().command
    if command == "check":
        replay()
    elif command == "initialize":
        initialize_managed()
    elif command == "isolate":
        state.publish("restoring")
    elif command == "finish-restore":
        quarantine_restored()
    elif command == "rotate-keys":
        rotate_keys()
    elif command == "store-backup":
        state.require_open()
        print(store(sys.stdin.buffer))  # noqa: T201 - only generated backup UUID


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("运维操作未完成；保持隔离，请核对输入和独立日志") from None
