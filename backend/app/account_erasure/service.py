"""Publish irreversible intent before waiting for an in-flight model's User lock."""

import hmac
import json
import secrets
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

import procrastinate
from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel import Session, select

from app.account_erasure import journal
from app.account_erasure.inventory import TABLES
from app.account_erasure.models import AccountErasure, JournalState
from app.core.db import engine
from app.core.security import verify_password
from app.core.verification import token_hash
from app.deletion.quality import erase_unreferenced, hashes, lock_hashes
from app.deletion.service import authentication_digest
from app.models import User
from app.quality.models import QualityReport
from app.training.projection import erasure_lock_key
from app.training.queue import DSN


def denied(user_id: uuid.UUID) -> bool:
    try:
        return journal.contains(user_id)
    except (OSError, ValueError, RuntimeError, sqlite3.Error):
        raise HTTPException(503, "独立删除记录不可用；为防恢复旧账号，暂不开放访问或调用")


def require_account(user_id: uuid.UUID) -> None:
    if denied(user_id):
        raise HTTPException(401, "账号已请求注销，旧会话及新调用不可再使用")


def require_ready(session: Session) -> None:
    from app.operations.state import require_open

    try:
        require_open()
        identity, sequence = journal.head()
        state = session.get(JournalState, 1, populate_existing=True)
        if not state or state.identity != identity or state.sequence != sequence:
            raise ValueError
    except (OSError, ValueError, RuntimeError, sqlite3.Error):
        raise HTTPException(503, "须先连接独立删除日志并完成恢复重放，才可开放 API 或任务")


def result_permission(session: Session, user_id: uuid.UUID) -> None:
    # Only this short row lock serializes publication with final intent. Never
    # acquire User here: a caller may already hold it in another HTTP session.
    item = session.exec(select(AccountErasure).where(AccountErasure.user_id == user_id).with_for_update().execution_options(populate_existing=True)).one_or_none()
    if item and item.accepted_at:
        raise HTTPException(409, "账号已请求注销")
    require_account(user_id)


def preview(session: Session, user_id: uuid.UUID, password: str) -> tuple[AccountErasure, str, dict[str, int]]:
    require_ready(session)
    user = session.exec(select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True)).one_or_none()
    require_account(user_id)
    valid, _ = verify_password(password, user.hashed_password if user else "")
    if not user or not user.is_active or not valid:
        raise HTTPException(403, "重新认证失败，请核对当前密码")
    item = session.exec(select(AccountErasure).where(AccountErasure.user_id == user_id).with_for_update()).one_or_none()
    if item and item.accepted_at:
        raise HTTPException(409, "注销已经受理")
    secret = secrets.token_urlsafe(32)
    item = item or AccountErasure(user_id=user_id)
    item.request_id = uuid.uuid4()
    item.authentication_digest = authentication_digest(user.hashed_password)
    item.receipt_hash = token_hash(secret)
    item.expires_at = datetime.now(UTC) + timedelta(minutes=10)
    session.add(item)
    counts = {
        table: session.execute(text(f'SELECT count(*) FROM "{table}" t WHERE account_row_owner(:table,to_jsonb(t))=:owner'), {"table": table, "owner": user_id}).scalar_one()
        for table in TABLES
    }
    session.commit()
    session.refresh(item)
    return item, secret, {k: v for k, v in counts.items() if v}


def receipt(session: Session, request_id: uuid.UUID, secret: str, *, lock: bool = False) -> AccountErasure:
    query = select(AccountErasure).where(AccountErasure.request_id == request_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    item = session.exec(query).one_or_none()
    if not item or not hmac.compare_digest(item.receipt_hash, token_hash(secret)):
        raise HTTPException(404, "注销回执不存在或凭据不匹配")
    return item


def confirm(session: Session, request_id: uuid.UUID, secret: str) -> AccountErasure:
    item = receipt(session, request_id, secret, lock=True)
    if item.accepted_at:
        return item
    user = session.get(User, item.user_id, populate_existing=True)
    if not user or item.expires_at <= datetime.now(UTC) or authentication_digest(user.hashed_password) != item.authentication_digest:
        raise HTTPException(409, "重新认证已失效，请重新预览注销")
    # Serialize append against the exact applied prefix. Another confirmation
    # cannot jump over a durable entry whose PostgreSQL transaction crashed.
    state = session.exec(select(JournalState).where(JournalState.id == 1).with_for_update().execution_options(populate_existing=True)).one_or_none()
    if not state:
        raise HTTPException(503, "独立删除日志尚未绑定")
    require_ready(session)
    # SQLite commit is durable before PostgreSQL intent/queue commit.
    entry = journal.append(item.user_id, item.request_id, datetime.now(UTC), item.receipt_hash)
    item.accepted_at = entry.accepted_at
    state.sequence = max(state.sequence, entry.sequence)
    from app.account_erasure.worker import erase_account

    app = procrastinate.App(connector=procrastinate.SyncPsycopgConnector(conninfo=DSN))
    task = app.task(name="account.erase")(erase_account.func)
    task.configure(connection=session.connection().connection.driver_connection, lock=str(item.user_id)).defer(user_id=str(item.user_id))
    session.add(item)
    session.add(state)
    session.commit()
    session.refresh(item)
    return item


def drain_permission(session: Session, item: AccountErasure) -> None:
    # Publish intent first so login/probes reject immediately. Only then drain
    # the existing HTTP permission, without holding AccountErasure or Config.
    # A successful confirm response therefore cannot precede an old dispatch.
    owner = item.user_id
    session.commit()
    session.exec(select(User).where(User.id == owner).with_for_update()).one_or_none()
    session.commit()
    session.refresh(item)


def purge(user_id: uuid.UUID) -> None:
    if not denied(user_id):
        raise RuntimeError("No independently durable account erasure intent")
    with Session(engine) as session:
        # Drain the existing HTTP permission before removing task rows. Watchers
        # see SQLite intent without waiting for this lock (also version=None).
        session.exec(select(User).where(User.id == user_id).with_for_update()).one_or_none()
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": erasure_lock_key(user_id)})
        item = session.exec(select(AccountErasure).where(AccountErasure.user_id == user_id).with_for_update().execution_options(populate_existing=True)).one()
        if item.completed_at:
            return
        if not item.accepted_at:
            raise RuntimeError("Replay must install confirmed intent first")
        reports = session.exec(select(QualityReport).where(QualityReport.user_id == user_id)).all()
        blobs = {sha for r in reports if r.report for sha in hashes(r.report)}
        lock_hashes(session, blobs)
        params = {"owner": user_id, "request": item.request_id}
        # Capture permits while every parent still exists; later FK deletion order
        # never removes the authorization proof for another table's immutable guard.
        for table in TABLES:
            session.execute(text(f'INSERT INTO account_erasure_permit(user_id,table_name,row_key,request_id) SELECT :owner,CAST(:table AS text),account_row_key(:table,to_jsonb(t)),:request FROM "{table}" t WHERE account_row_owner(:table,to_jsonb(t))=:owner ON CONFLICT DO NOTHING'), params | {"table": table})
        for sha in sorted(blobs):
            session.execute(text("INSERT INTO account_erasure_permit VALUES (:owner,'quality_evidence',:key,:request) ON CONFLICT DO NOTHING"), params | {"key": json.dumps([sha])})
        jobs: list[int] = []
        for task, key, table in (
            ("training.generate", "run_id", "training_run"),
            ("project.analyze", "run_id", "project_run"),
            ("topic.analyze", "topic_job_id", "topic_job"),
            ("training.check_submission", "submission_id", "training_submission"),
            ("training.evaluate", "run_id", "training_run"),
            ("training.review", "run_id", "training_run"),
            ("training.concept", "help_id", "concept_help"),
        ):
            jobs.extend(session.execute(text("SELECT j.id FROM procrastinate_jobs j JOIN account_erasure_permit p ON p.row_key::jsonb->>0 = j.args->>:key WHERE j.task_name=:task AND p.user_id=:owner AND p.table_name=:table"), params | {"task": task, "key": key, "table": table}).scalars())
        session.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        for table in TABLES:
            session.execute(text(f'DELETE FROM "{table}" t USING account_erasure_permit p WHERE p.user_id=:owner AND p.request_id=:request AND p.table_name=:table AND p.row_key=account_row_key(:table,to_jsonb(t))'), params | {"table": table})
        if jobs:
            session.execute(text("DELETE FROM procrastinate_jobs WHERE id=ANY(:jobs)"), {"jobs": jobs})
        erase_unreferenced(session, blobs)
        item.completed_at = datetime.now(UTC)
        item.authentication_digest = ""
        session.add(item)
        session.execute(text("DELETE FROM account_erasure_permit WHERE user_id=:owner"), params)
        session.commit()
