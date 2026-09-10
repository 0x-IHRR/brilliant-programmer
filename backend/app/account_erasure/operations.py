"""Trusted local initialization/replay, never infer a restored database is fresh."""

import argparse
from datetime import UTC, datetime

from sqlalchemy import text
from sqlmodel import Session, select

from app.account_erasure import journal
from app.account_erasure.models import AccountErasure, JournalState
from app.account_erasure.service import purge
from app.core.db import engine
from app.models import User


def initialize(*, live_upgrade: bool = False) -> None:
    with Session(engine) as session:
        if session.get(JournalState, 1):
            raise RuntimeError("已绑定独立日志，不能重新初始化")
        if not live_upgrade and session.exec(select(User)).first():
            raise RuntimeError("非空账号库不能当作新安装；恢复必须使用已有独立日志重放")
        identity = journal.initialize()
        session.add(JournalState(identity=identity))
        session.commit()


def replay() -> None:
    from app.account_erasure.retention import expire

    expire()
    identity, entries = journal.read()  # Missing file cannot be repaired by creating one.
    with Session(engine) as session:
        state = session.get(JournalState, 1)
        if state and state.identity != identity:
            raise RuntimeError("数据库与独立删除日志身份不匹配")
        if state and state.sequence > (entries[-1].sequence if entries else 0):
            raise RuntimeError("独立删除日志落后，禁止恢复访问")
        for entry in entries:
            item = session.get(AccountErasure, entry.user_id)
            if item and item.accepted_at and item.request_id != entry.request_id:
                raise RuntimeError("注销身份冲突，禁止开放访问")
            if not item:
                item = AccountErasure(user_id=entry.user_id, request_id=entry.request_id, authentication_digest="", receipt_hash=entry.receipt_hash, expires_at=entry.accepted_at)
            item.request_id = entry.request_id
            if entry.receipt_hash:
                item.receipt_hash = entry.receipt_hash
            item.accepted_at = entry.accepted_at
            session.add(item)
        session.commit()
    for entry in entries:
        purge(entry.user_id)
    with Session(engine) as session:
        state = session.get(JournalState, 1) or JournalState(identity=identity)
        state.sequence = entries[-1].sequence if entries else 0
        session.add(state)
        session.commit()


def audit_deadlines(now: datetime | None = None) -> None:
    instant = now or datetime.now(UTC)
    with Session(engine) as session:
        missed = session.execute(text("SELECT count(*) FROM account_erasure WHERE accepted_at IS NOT NULL AND ((completed_at IS NULL AND accepted_at <= :now - interval '24 hours') OR completed_at > accepted_at + interval '24 hours')"), {"now": instant}).scalar_one()
        if missed:
            raise RuntimeError("存在超过 24 小时仍未清除的在线账号资料；禁止声明删除完成")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["initialize-empty", "adopt-live", "replay", "audit"])
    operation = parser.parse_args().operation
    if operation == "initialize-empty":
        initialize()
    elif operation == "adopt-live":
        # Explicit operator-only upgrade path, never called by API or migration.
        initialize(live_upgrade=True)
    elif operation == "replay":
        replay()
    else:
        audit_deadlines()


if __name__ == "__main__":
    main()
