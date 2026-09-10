"""Controlled old-0028 PostgreSQL dump restoration; independent SQLite stays outside.

Run from backend with the dedicated synthetic database/Compose configured.
Keeps the isolated databases and dump for review; volume cleanup is coordinator-owned.
"""
import io
import json
import os
import secrets
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlmodel import Session

from app.account_erasure import journal, operations, retention
from app.account_erasure.models import JournalState
from app.account_erasure.service import require_ready
from app.core.config import settings
from app.core.db import engine
from app.core.security import create_access_token, get_password_hash
from app.core.verification import token_hash
from app.main import app
from app.model_config.models import ModelConfig
from app.model_config.service import decrypt, encrypt
from app.models import LoginSession, User
from app.training.draft_models import TrainingDraft
from app.training.models import TrainingRun
from app.training.schema import Candidate
from tests.test_guided import frozen


def snapshot(session, owner):
    result = {}
    for table in ('user', 'model_config', 'loginsession', 'training_run', 'training_draft'):
        where = 't.id=:owner' if table == 'user' else 't.user_id=:owner'
        if table == 'training_draft':
            where = 't.run_id IN (SELECT id FROM training_run WHERE user_id=:owner)'
        result[table] = session.execute(text(f'SELECT row_to_json(t)::text FROM "{table}" t WHERE {where} ORDER BY row_to_json(t)::text'), {'owner':owner}).scalars().all()
    return result


def child(mode: str, owner: uuid.UUID, other: uuid.UUID) -> None:
    if mode == 'seed':
        candidate, sources = frozen.__wrapped__()
        with Session(engine) as session:
            for identity in (owner, other):
                session.add(User(id=identity, email=f'{identity}@synthetic.invalid', hashed_password=get_password_hash('synthetic-local-only'), email_verified=True))
            session.commit()
            for identity in (owner, other):
                config = ModelConfig(user_id=identity, service_url='https://synthetic.invalid/v1', model_id='synthetic', encrypted_key=b'', key_version=settings.MODEL_ACTIVE_KEY_VERSION)
                config.encrypted_key = encrypt(config, SecretStr('fake-backup-key-only'))
                session.add(config)
                run = TrainingRun(user_id=identity, config_version=config.version, destination=config.service_url, model_id='synthetic', selection={'entry':'random'}, target=candidate.target.model_dump(mode='json'), sources=[s.model_dump(mode='json') for s in sources], candidate=candidate.model_dump(mode='json'), status='completed', code='ok')
                session.add(run)
                session.flush()
                session.add(LoginSession(user_id=identity, expires_at=datetime.now(UTC) + timedelta(days=1)))
                session.add(TrainingDraft(run_id=run.id, version=uuid.uuid4(), request_id=uuid.uuid4(), saved_at=datetime.now(UTC), progress={'answers':[{'judgment_id':candidate.judgments[0].id, 'value':None, 'reason':'synthetic private unfinished draft'}], 'step':'judgments', 'based_on_submission_id':None}))
            session.commit()
            import procrastinate

            from app.training.queue import DSN
            from app.training.worker import generate_training

            app_queue = procrastinate.App(connector=procrastinate.SyncPsycopgConnector(conninfo=DSN))
            task = app_queue.task(name='training.generate')(generate_training.func)
            old_run = session.execute(text('SELECT id FROM training_run WHERE user_id=:owner'), {'owner':owner}).scalar_one()
            task.configure(connection=session.connection().connection.driver_connection).defer(run_id=str(old_run))
            session.commit()
            preserved = snapshot(session, other)
        target = journal.path().parent / 'other-state.json'
        with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as output:
            json.dump(preserved, output, sort_keys=True)
        return
    with Session(engine) as session:
        for identity in (owner, other):
            assert all(snapshot(session, identity).values())
            assert decrypt(session.get(ModelConfig, identity)).get_secret_value() == 'fake-backup-key-only'
        assert session.get(JournalState, 1) is None  # Real old backup had no binding.
        try:
            require_ready(session)
        except HTTPException as error:
            assert error.status_code == 503
        else:
            raise AssertionError('Restored old data opened without replay')
    # Execute the production module, not the tests/training_worker entry point.
    missing_env = dict(os.environ, ACCOUNT_ERASURE_JOURNAL=str(journal.path().parent / 'missing.sqlite3'))
    failed = subprocess.run([sys.executable, '-m', 'app.training.worker'], env=missing_env, capture_output=True, timeout=10)
    assert failed.returncode != 0
    with Session(engine) as session:
        assert session.get(User, owner) is not None
        assert session.execute(text("SELECT count(*) FROM procrastinate_jobs WHERE task_name='training.generate' AND status='todo'")).scalar_one() == 1
    import procrastinate

    from app.account_erasure.worker import erase_account
    from app.training.queue import DSN

    actual_queue = procrastinate.App(connector=procrastinate.SyncPsycopgConnector(conninfo=DSN))
    sentinel = actual_queue.task(name='account.erase')(erase_account.func)
    with Session(engine) as session:
        sentinel_id = sentinel.configure(connection=session.connection().connection.driver_connection).defer(user_id=str(owner))
        session.commit()
    with (journal.path().parent / 'production-worker.log').open('a') as output:
        worker = subprocess.Popen([sys.executable, '-m', 'app.training.worker'], stdout=output, stderr=output)
    try:
        deadline = time.monotonic() + 15
        while True:
            with Session(engine) as session:
                gone = session.get(User, owner) is None
                consumed = session.execute(text('SELECT status FROM procrastinate_jobs WHERE id=:id'), {'id':sentinel_id}).scalar_one()
            if gone and consumed == 'succeeded':
                break
            assert worker.poll() is None
            assert time.monotonic() < deadline
            time.sleep(.05)
    finally:
        worker.terminate()
        worker.wait(timeout=5)
    operations.replay()
    with Session(engine) as session:
        require_ready(session)
        assert session.get(User, owner) is None
        assert all(not rows for rows in snapshot(session, owner).values())
        assert snapshot(session, other) == json.loads((journal.path().parent / 'other-state.json').read_text())
        assert session.get(User, other) is not None
        assert session.execute(text('SELECT count(*) FROM training_run WHERE user_id=:owner'), {'owner': owner}).scalar_one() == 0
        remaining = session.execute(text('SELECT candidate FROM training_run WHERE user_id=:owner'), {'owner': other}).scalar_one()
        Candidate.model_validate(remaining)
    operations.audit_deadlines()
    with Session(engine) as session:
        existing_session = session.execute(text('SELECT id FROM loginsession WHERE user_id=:owner'), {'owner':other}).scalar_one()
        run_id = session.execute(text('SELECT id FROM training_run WHERE user_id=:owner'), {'owner':other}).scalar_one()
    auth = {'Authorization': 'Bearer ' + create_access_token(other, timedelta(minutes=5), existing_session)}
    _, entries = journal.read()
    request = next(e.request_id for e in entries if e.user_id == owner)
    secret = os.environ['BP32_RECEIPT_KEY']
    with TestClient(app, client=(f'restore-{owner}', 50000)) as client:
        readable = client.get(f'/api/v1/training/tasks/{run_id}', headers=auth)
        assert readable.status_code == 200 and readable.json()['case']
        status = client.post(f'/api/v1/account-erasure/{request}/status', json={'receipt_key': secret})
        assert status.status_code == 200 and status.json()['completed_at']
        repeated = client.post(f'/api/v1/account-erasure/{request}/confirm', json={'receipt_key': secret, 'confirmation':'注销本账号并永久删除全部私有资料'})
        assert repeated.status_code == 202 and repeated.json() == status.json()
        invalid = client.post(f'/api/v1/account-erasure/{request}/status', json={'receipt_key': 'x' * 43})
        assert invalid.status_code == 404
    assert secret.encode() not in journal.path().read_bytes()
    print('Restored old 0028: initially blocked; replay twice removed target, preserved readable other candidate.')  # noqa: T201


def main() -> None:
    if len(sys.argv) > 1:
        child(sys.argv[1], uuid.UUID(sys.argv[2]), uuid.UUID(sys.argv[3]))
        return
    container = os.environ.get('ACCOUNT_ERASURE_DB_CONTAINER', 'bp-issue-32-db-1')
    marker = uuid.uuid4().hex[:10]
    source, restored = f'bp32_old_{marker}', f'bp32_restored_{marker}'
    owner, other, request = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    artifact = Path(f'/tmp/bp32-restore-{marker}')
    artifact.mkdir(mode=0o700)
    settings.ACCOUNT_ERASURE_JOURNAL = str(artifact / 'independent.sqlite3')
    identity = journal.initialize()
    base = make_url(str(settings.DATABASE_URL))
    with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as connection:
        for name in (source, restored):
            connection.execute(text(f'CREATE DATABASE "{name}"'))
    secret = secrets.token_urlsafe(32)
    env = dict(os.environ, ACCOUNT_ERASURE_JOURNAL=settings.ACCOUNT_ERASURE_JOURNAL, BP32_RECEIPT_KEY=secret)
    def run(command, database):
        local = dict(env, DATABASE_URL=base.set(database=database).render_as_string(hide_password=False))
        subprocess.run(command, env=local, check=True)
    run([sys.executable, '-m', 'alembic', 'upgrade', '0028_permanent_deletion'], source)
    run([sys.executable, __file__, 'seed', str(owner), str(other)], source)
    dump = subprocess.run(['docker', 'exec', container, 'pg_dump', '-U', base.username, '-d', source, '-Fc', '--no-owner'], check=True, capture_output=True).stdout
    stored_at = datetime.now(UTC)
    dump_id = retention.store(io.BytesIO(dump), stored_at)
    journal.append(owner, request, stored_at, token_hash(secret))  # After backup; cannot exist inside dump.
    subprocess.run(['docker', 'exec', '-i', container, 'pg_restore', '-U', base.username, '-d', restored, '--no-owner', '--exit-on-error'], input=dump, check=True)
    run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], restored)
    run([sys.executable, __file__, 'verify', str(owner), str(other)], restored)
    assert retention.expire(stored_at + timedelta(days=30)) == 1
    assert not (retention.directory() / f'{dump_id}.dump').exists()
    assert journal.read()[0] == identity and journal.contains(owner)
    print(f'Actual dump expired at 30d; independent marker retained. Synthetic DBs: {source}, {restored}; artifact: {artifact}')  # noqa: T201


if __name__ == '__main__':
    main()
