"""Synthetic accounts only; real journal, database guards and authentication."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session, select

from app.account_erasure.models import AccountErasure
from app.account_erasure.service import purge
from app.core.db import engine
from app.main import app
from app.models import LoginSession, User
from tests import test_accounts
from tests.test_deletions import create_run
from tests.test_model_config import account


@pytest.fixture
def client(monkeypatch):
    with TestClient(app, client=(f"erase-account-{uuid.uuid4()}", 50000)) as client:
        monkeypatch.setattr(test_accounts, "client", client)
        yield client


def prepared(client, auth):
    response = client.post('/api/v1/account-erasure/preview', headers=auth, json={'password':'local-test-password-only'})
    assert response.status_code == 200, response.text
    return response.json()


def accepted(client, preview):
    body = {'receipt_key': preview['receipt_key'], 'confirmation':'注销本账号并永久删除全部私有资料'}
    response = client.post(f"/api/v1/account-erasure/{preview['request_id']}/confirm", json=body)
    assert response.status_code == 202, response.text
    return response.json()


def test_intent_blocks_sessions_and_purge_removes_account_and_private_graph(client):
    owner, auth = account()
    other, other_auth = account()
    run = create_run(owner)
    other_run = create_run(other)
    preview = prepared(client, auth)
    accepted(client, preview)
    assert client.get('/api/v1/users/me',headers=auth).status_code == 401
    assert client.get('/api/v1/users/me',headers=other_auth).status_code == 200
    purge(owner)
    with Session(engine) as session:
        assert session.get(User, owner) is None
        assert not session.exec(select(LoginSession).where(LoginSession.user_id==owner)).all()
        from app.training.models import TrainingRun
        assert session.get(TrainingRun,run) is None
        assert session.get(TrainingRun,other_run).selection['private']=='synthetic-delete-me'
        assert session.get(AccountErasure,owner).completed_at is not None
    result = accepted(client,preview)
    assert result['completed_at']
    response=client.post(f"/api/v1/account-erasure/{preview['request_id']}/status",json={'receipt_key':preview['receipt_key']})
    assert response.json()==result
    assert client.get('/api/v1/users/me',headers=auth).status_code == 401


def test_receipt_wrong_key_password_and_owner_cannot_erase(client):
    owner,auth=account()
    other,other_auth=account()
    assert client.post('/api/v1/account-erasure/preview',headers=auth,json={'password':'wrong'}).status_code==403
    p=prepared(client,auth)
    q=prepared(client,other_auth)
    assert client.post(f"/api/v1/account-erasure/{p['request_id']}/confirm",json={'receipt_key':q['receipt_key'],'confirmation':'注销本账号并永久删除全部私有资料'}).status_code==404
    with Session(engine) as s:
        assert s.get(User,owner) and s.get(User,other)
        with pytest.raises(DBAPIError):
            s.execute(text('DELETE FROM "user" WHERE id=:id'),{'id':owner})
            s.commit()
        s.rollback()


@pytest.mark.parametrize('saved', [False, True])
def test_real_probe_without_or_with_config_observes_intent_and_keeps_received_usage(client, tmp_path, monkeypatch, saved):
    import socket
    import ssl
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from app.model_config import connection
    from app.model_config.usage import ProbeAttempt
    from tests.test_model_config import FAKE_KEY, body
    from tests.test_training import provider as provider_fixture

    # The existing actual TLS fixture; only DNS and trust map its fake destination.
    fixture = provider_fixture.__wrapped__(tmp_path)
    provider = next(fixture)
    original_resolve, original_context = socket.getaddrinfo, ssl.create_default_context
    monkeypatch.setattr(socket, 'getaddrinfo', lambda host, *args, **kwargs: original_resolve('127.0.0.1' if host == 'provider.example.com' else host, *args, **kwargs))
    monkeypatch.setattr(connection, 'public_ip', lambda ip: ip == '127.0.0.1')
    monkeypatch.setattr(ssl, 'create_default_context', lambda: original_context(cafile=provider['cert']))
    provider['mode'] = 'partial_usage'
    consumed = Event()
    stream = connection.httpcore.Response.aiter_stream

    async def observe(response):
        raw = bytearray()
        async for chunk in stream(response):
            yield chunk
            raw.extend(chunk)
            if connection.received_usage(bytes(raw), 'text/event-stream', False)['prompt_tokens'] == 11:
                consumed.set()

    monkeypatch.setattr(connection.httpcore.Response, 'aiter_stream', observe)
    try:
        owner,auth = account()
        if saved:
            result=client.put('/api/v1/model-config',headers=auth,json=body(service_url=provider['url']))
            assert result.status_code == 200, result.text
        preview=prepared(client,auth)
        with ThreadPoolExecutor() as executor:
            future=executor.submit(client.post,'/api/v1/model-config/probe/test',headers=auth,json={'service_url':provider['url'],'model_id':'fake','api_key':FAKE_KEY,'disclosure_accepted':True})
            assert consumed.wait(5)
            try:
                result=executor.submit(accepted,client,preview).result(timeout=3)
                assert result['accepted_at'] and result['completed_at'] is None
                response=future.result(timeout=5)
                assert response.status_code == 200, response.text
                value=response.json()
                assert value['code']=='cancelled'
                assert value['attempts']==[{'number':1,'code':'cancelled','prompt_tokens':11,'completion_tokens':None,'total_tokens':20}]
                assert client.post('/api/v1/model-config/probe/test',headers=auth,json={'service_url':provider['url'],'model_id':'fake','api_key':FAKE_KEY,'disclosure_accepted':True}).status_code==401
                assert len(provider['requests'])==1
                with Session(engine) as session:
                    attempt=session.exec(select(ProbeAttempt).where(ProbeAttempt.user_id==owner)).one()
                    assert (attempt.code,attempt.prompt_tokens,attempt.completion_tokens,attempt.total_tokens)==('cancelled',11,None,20)
                purge(owner)
                with Session(engine) as session:
                    assert not session.exec(select(ProbeAttempt).where(ProbeAttempt.user_id==owner)).all()
            finally:
                provider['release'].set()
    finally:
        provider['release'].set()
        try:
            next(fixture)
        except StopIteration:
            pass


def test_invalid_erasure_inputs_never_echo_private_values(client):
    _, auth = account()
    secret = "synthetic-sensitive-never-echo"
    cases = [
        ("preview", {"password": {"private": secret}}, auth),
        (f"{uuid.uuid4()}/confirm", {"receipt_key": secret, "confirmation": secret}, {}),
        (f"{uuid.uuid4()}/status", {"receipt_key": {"private": secret}}, {}),
    ]
    for path, body, headers in cases:
        response = client.post(f"/api/v1/account-erasure/{path}", headers=headers, json=body)
        assert response.status_code == 422
        assert secret not in response.text
        assert "input" not in response.text


def test_intent_wins_while_acquired_permission_has_not_returned_to_caller(client, monkeypatch):
    import asyncio
    import time
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from fastapi import HTTPException

    from app.account_erasure import journal
    from app.training import gate

    owner, auth = account()
    p = prepared(client, auth)
    acquired, release = Event(), Event()
    original = gate.acquire
    entered = []

    def blocked_acquire(*args):
        value = original(*args)
        acquired.set()
        assert release.wait(5)
        return value

    async def dispatch():
        try:
            async with gate.call_permission(owner, None):
                entered.append('HTTP permission yielded')
        except HTTPException as error:
            return error.status_code
        return 200

    monkeypatch.setattr(gate, 'acquire', blocked_acquire)
    with ThreadPoolExecutor(max_workers=2) as pool:
        call = pool.submit(asyncio.run, dispatch())
        assert acquired.wait(5)
        confirmation = pool.submit(accepted, client, p)
        try:
            deadline = time.monotonic() + 5
            while not journal.contains(owner):
                assert time.monotonic() < deadline
                time.sleep(.01)
            assert not confirmation.done()  # Intent is visible before draining User.
            assert client.get('/api/v1/users/me', headers=auth).status_code == 401
            release.set()
            assert call.result(timeout=5) == 401
            assert confirmation.result(timeout=5)['accepted_at']
            assert entered == []
        finally:
            release.set()
    purge(owner)


def test_durable_journal_commit_before_database_intent_replays_before_access(client):
    from datetime import UTC, datetime

    from app.account_erasure import journal, operations
    from app.account_erasure.models import JournalState

    owner, auth = account()
    other, other_auth = account()
    p = prepared(client, auth)
    run = create_run(owner)
    other_run = create_run(other)
    # Exact crash gap: external commit survives, PG intent/queue never committed.
    entry = journal.append(owner, uuid.UUID(p['request_id']), datetime.now(UTC))
    with Session(engine) as session:
        assert session.get(AccountErasure, owner).accepted_at is None
        assert session.get(JournalState, 1).sequence < entry.sequence
    try:
        assert client.get('/api/v1/users/me', headers=auth).status_code == 503
        assert client.get('/api/v1/users/me', headers=other_auth).status_code == 503
        operations.replay()
        operations.replay()
        with Session(engine) as session:
            from app.training.models import TrainingRun
            assert session.get(User, owner) is None
            assert session.get(TrainingRun, run) is None
            assert session.get(TrainingRun, other_run) is not None
            assert session.get(User, other) is not None
        assert client.get('/api/v1/users/me', headers=auth).status_code == 401
        assert client.get('/api/v1/users/me', headers=other_auth).status_code == 200
        response = client.post(f"/api/v1/account-erasure/{p['request_id']}/status", json={'receipt_key': p['receipt_key']})
        assert response.status_code == 200 and response.json()['completed_at']
    finally:
        operations.replay()


def test_online_deadline_reports_actual_pending_without_claiming_completion(client):
    from datetime import datetime, timedelta

    from app.account_erasure.operations import audit_deadlines

    owner, auth = account()
    p = prepared(client, auth)
    result = accepted(client, p)
    accepted_at = datetime.fromisoformat(result['accepted_at'])
    try:
        audit_deadlines(accepted_at + timedelta(hours=24, microseconds=-1))
        with pytest.raises(RuntimeError, match='24'):
            audit_deadlines(accepted_at + timedelta(hours=24))
        with Session(engine) as session:
            assert session.get(User, owner) is not None
            assert session.get(AccountErasure, owner).completed_at is None
    finally:
        purge(owner)
    audit_deadlines(accepted_at + timedelta(days=2))


def test_second_account_confirmation_cannot_skip_unapplied_journal_entry(client):
    from datetime import UTC, datetime

    from app.account_erasure import journal, operations
    from app.account_erasure.models import JournalState

    a, auth_a = account()
    b, auth_b = account()
    pa, pb = prepared(client, auth_a), prepared(client, auth_b)
    with Session(engine) as session:
        prior = session.get(JournalState, 1).sequence
    journal.append(a, uuid.UUID(pa['request_id']), datetime.now(UTC))
    try:
        response = client.post(f"/api/v1/account-erasure/{pb['request_id']}/confirm", json={'receipt_key': pb['receipt_key'], 'confirmation':'注销本账号并永久删除全部私有资料'})
        assert response.status_code == 503
        with Session(engine) as session:
            assert session.get(JournalState, 1).sequence == prior
            assert session.get(AccountErasure, b).accepted_at is None
        assert not journal.contains(b)
        assert client.get('/api/v1/users/me', headers=auth_b).status_code == 503
    finally:
        operations.replay()
    assert client.get('/api/v1/users/me', headers=auth_b).status_code == 200


def test_record_erasure_empty_quality_report_does_not_block_account_erasure(client, tmp_path):
    from app.account_erasure import operations
    from app.quality.import_report import load
    from app.quality.import_report import save as import_report
    from app.quality.models import QualityReport
    from app.training.models import TrainingRun
    from tests.test_model_config import save
    from tests.test_quality_import import bundle

    owner, auth = account()
    config = save(auth).json()
    path, digest, _, _ = bundle(tmp_path, owner, config)
    report, digest, files = load(path, digest, tmp_path)
    with Session(engine) as session:
        import_report(session, report, digest, files)
        session.commit()
    run = create_run(owner)
    with Session(engine) as session:
        row = session.get(TrainingRun, run)
        row.sources = [{'text': files[report.cases[0].sources[0].text_sha256].decode()}]
        session.add(row)
        session.commit()
    preview = client.post('/api/v1/records/deletions/preview', headers=auth, json={'kind':'training', 'target_id':str(run), 'password':'local-test-password-only'})
    assert preview.status_code == 200, preview.text
    response = client.post(f"/api/v1/records/deletions/{preview.json()['id']}/confirm", headers=auth, json={'confirmation':'永久删除所列资料及副本'})
    assert response.status_code == 200, response.text
    with Session(engine) as session:
        assert session.get(QualityReport, report.artifact_id).report == {}
    accepted(client, prepared(client, auth))
    operations.replay()
    operations.replay()
    with Session(engine) as session:
        assert session.get(User, owner) is None
        assert session.get(QualityReport, report.artifact_id) is None


def test_replay_snapshot_cannot_regress_a_new_contiguous_confirmation(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from app.account_erasure import operations
    from app.account_erasure.models import JournalState
    from app.account_erasure.service import require_ready

    anchor, anchor_auth = account()
    accepted(client, prepared(client, anchor_auth))
    purge(anchor)
    _, auth = account()
    p = prepared(client, auth)
    paused, release = Event(), Event()
    original = operations.purge
    first = True

    def pause_once(identity):
        nonlocal first
        if first:
            first = False
            paused.set()
            assert release.wait(5)
        original(identity)

    monkeypatch.setattr(operations, 'purge', pause_once)
    with ThreadPoolExecutor(max_workers=1) as pool:
        replay = pool.submit(operations.replay)
        try:
            assert paused.wait(5)
            accepted(client, p)
            with Session(engine) as session:
                newest = session.get(JournalState, 1).sequence
            release.set()
            replay.result(timeout=5)
            with Session(engine) as session:
                assert session.get(JournalState, 1).sequence == newest
                require_ready(session)
        finally:
            release.set()
            replay.result(timeout=5)
            operations.replay()


def test_independent_worker_erases_queued_account_without_outbound_and_restart_is_safe(client, tmp_path):
    import time

    from app.model_config.models import ModelConfig
    from tests.test_model_config import save
    from tests.test_training import provider as provider_fixture
    from tests.test_training import start_worker, stop_worker

    fixture = provider_fixture.__wrapped__(tmp_path)
    provider = next(fixture)
    process = None
    try:
        owner, auth = account()
        config = save(auth, service_url=provider['url']).json()
        queued = client.post('/api/v1/training/random', headers=auth, json={'disclosure_accepted': True, 'expected_config_version': config['version']})
        assert queued.status_code == 202, queued.text
        run = queued.json()['id']
        p = prepared(client, auth)
        accepted(client, p)
        process, _ = start_worker(tmp_path, provider, run)
        deadline = time.monotonic() + 15
        while True:
            with Session(engine) as session:
                completed = session.get(AccountErasure, owner).completed_at
            if completed:
                break
            assert time.monotonic() < deadline
            time.sleep(.05)
        stop_worker(process)
        process = None
        with Session(engine) as session:
            assert session.get(User, owner) is None
            assert session.get(ModelConfig, owner) is None
            assert session.execute(text("SELECT count(*) FROM procrastinate_jobs WHERE args->>'run_id'=:id"), {'id':run}).scalar_one() == 0
        assert provider['requests'] == []
        # A restarted actual worker may consume the minimal duplicate erase job;
        # no deleted run or credential is recreated and the receipt stays usable.
        import procrastinate

        from app.account_erasure.worker import erase_account
        from app.training.queue import DSN

        app_queue = procrastinate.App(connector=procrastinate.SyncPsycopgConnector(conninfo=DSN))
        task = app_queue.task(name='account.erase')(erase_account.func)
        with Session(engine) as session:
            job = task.configure(connection=session.connection().connection.driver_connection).defer(user_id=str(owner))
            session.commit()
        process, _ = start_worker(tmp_path, provider, run)
        deadline = time.monotonic() + 15
        while True:
            with Session(engine) as session:
                job_status = session.execute(text('SELECT status FROM procrastinate_jobs WHERE id=:id'), {'id':job}).scalar_one()
            if job_status == 'succeeded':
                break
            assert time.monotonic() < deadline
            assert job_status != 'failed'
            time.sleep(.05)
        result = client.post(f"/api/v1/account-erasure/{p['request_id']}/status", json={'receipt_key':p['receipt_key']})
        assert result.status_code == 200 and result.json()['completed_at']
        assert provider['requests'] == []
    finally:
        if process:
            stop_worker(process)
        provider['release'].set()
        fixture.close()


def test_account_erasure_preserves_shared_quality_bytes_until_last_live_owner(client, tmp_path):
    import hashlib

    from app.quality.import_report import load
    from app.quality.import_report import save as import_report
    from app.quality.models import QualityEvidence, QualityReport
    from tests.test_model_config import save
    from tests.test_quality_import import bundle

    owner, auth = account()
    other, other_auth = account()
    config = save(auth).json()
    path, digest, _, _ = bundle(tmp_path, owner, config)
    report, digest, files = load(path, digest, tmp_path)
    foreign = report.model_copy(update={'artifact_id':uuid.uuid4(), 'binding':report.binding.model_copy(update={'user_id':other})})
    with Session(engine) as session:
        import_report(session, report, digest, files)
        session.commit()
        import_report(session, foreign, hashlib.sha256(foreign.model_dump_json().encode()).hexdigest(), files)
        session.commit()
    accepted(client, prepared(client, auth))
    purge(owner)
    with Session(engine) as session:
        assert session.get(QualityReport, report.artifact_id) is None
        assert session.get(QualityReport, foreign.artifact_id).report == __import__('json').loads(foreign.model_dump_json())
        for sha, content in files.items():
            assert session.get(QualityEvidence, sha).content == content
    accepted(client, prepared(client, other_auth))
    purge(other)
    with Session(engine) as session:
        assert session.get(QualityReport, foreign.artifact_id) is None
        assert all(session.get(QualityEvidence, sha) is None for sha in files)


def test_exact_account_permits_reject_foreign_row_and_mixed_delete_rolls_back(client):
    import json

    from app.training.models import TrainingRun

    owner, auth = account()
    other, _ = account()
    own_run, other_run = create_run(owner), create_run(other)
    p = prepared(client, auth)
    accepted(client, p)
    with Session(engine) as session:
        params = {'owner':owner, 'request':uuid.UUID(p['request_id']), 'key':json.dumps([str(other_run)])}
        with pytest.raises(DBAPIError):
            session.execute(text("INSERT INTO account_erasure_permit VALUES (:owner,'training_run',:key,:request)"), params)
        session.rollback()
        session.execute(text("INSERT INTO account_erasure_permit VALUES (:owner,'training_run',:key,:request)"), params | {'key':json.dumps([str(own_run)])})
        with pytest.raises(DBAPIError):
            session.execute(text('DELETE FROM training_run WHERE id IN (:a,:b)'), {'a':own_run,'b':other_run})
        session.rollback()
        assert session.get(TrainingRun, own_run) is not None
        assert session.get(TrainingRun, other_run) is not None
        assert session.execute(text('SELECT count(*) FROM account_erasure_permit WHERE user_id=:id'),{'id':owner}).scalar_one() == 0
    purge(owner)
    with Session(engine) as session:
        assert session.get(TrainingRun, own_run) is None
        assert session.get(TrainingRun, other_run) is not None


def test_real_boss_review_revalidation_cycle_is_physically_erased(client, tmp_path, monkeypatch):
    from app.account_erasure.inventory import TABLES
    from tests import test_boss_revalidation
    from tests.test_training import provider as provider_fixture

    captured = []
    original_account = test_boss_revalidation.account

    def capture_account():
        result = original_account()
        captured.append(result)
        return result

    monkeypatch.setattr(test_boss_revalidation, 'account', capture_account)
    source = provider_fixture.__wrapped__(tmp_path)
    supplier = next(source)
    try:
        test_boss_revalidation.test_real_confirmed_promotion_review_new_same_stage_only_resolves(tmp_path, supplier)
    finally:
        source.close()
    assert len(captured) == 2
    owner, auth = captured[0]
    other, _ = captured[1]
    with Session(engine) as session:
        before = {
            table: session.execute(text(f'SELECT account_row_key(:table,to_jsonb(t)) FROM "{table}" t WHERE account_row_owner(:table,to_jsonb(t))=:owner'), {'table':table, 'owner':owner}).scalars().all()
            for table in TABLES
        }
        assert before['boss_revalidation'] and before['boss_promotion'] and before['score_review']
        assert len(before['boss_attempt']) >= 2
        foreign = session.get(User, other).model_dump()
    accepted(client, prepared(client, auth))
    purge(owner)
    with Session(engine) as session:
        for table, keys in before.items():
            if keys:
                assert session.execute(text(f'SELECT count(*) FROM "{table}" t WHERE account_row_key(:table,to_jsonb(t))=ANY(:keys)'), {'table':table, 'keys':list(keys)}).scalar_one() == 0, table
        assert session.get(User, other).model_dump() == foreign
    (tmp_path / 'erased-table-counts.json').write_text(__import__('json').dumps({table:len(keys) for table, keys in before.items() if keys}))


@pytest.mark.parametrize('kind', ['topic', 'jd', 'project'])
def test_valid_sources_account_erasure_preserves_other_owner_readable_graph(client, kind):
    from app.account_erasure.inventory import TABLES
    from tests.test_jds import seeded as seed_jd
    from tests.test_model_config import save
    from tests.test_project_training_rules import material
    from tests.test_project_updates import seeded as seed_project
    from tests.test_topics import seed_route

    participants = [account(), account()]
    identities = []
    for owner, auth in participants:
        config = save(auth).json()
        if kind == 'topic':
            identity = seed_route(owner)[0]
        elif kind == 'jd':
            identity, document = seed_jd(auth, config)
            selected = client.post(f'/api/v1/jds/{identity}/select', headers=auth, json={'document_id': document, 'role_index': 0})
            assert selected.status_code == 200, selected.text
        else:
            identity, _ = seed_project(owner, config, material.__wrapped__())
        identities.append(str(identity))
    path = {'topic':'/api/v1/topics', 'jd':'/api/v1/jds', 'project':'/api/v1/project-training'}[kind]
    owner, auth = participants[0]
    other, other_auth = participants[1]
    for (_, headers), identity in zip(participants, identities, strict=True):
        response = client.get(f'{path}/{identity}', headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()['current'] is not None
    before_read = client.get(f'{path}/{identities[1]}', headers=other_auth).json()
    before_list = client.get(path, headers=other_auth).json()
    with Session(engine) as session:
        keys = {
            table: session.execute(text(f'SELECT account_row_key(:table,to_jsonb(t)) FROM "{table}" t WHERE account_row_owner(:table,to_jsonb(t))=:owner'), {'table':table, 'owner':owner}).scalars().all()
            for table in TABLES
        }
        assert keys['topic_version'] and keys['model_config']
        if kind == 'jd':
            assert keys['jd_document'] and keys['jd_analysis'] and keys['jd_route']
        if kind == 'project':
            assert keys['project_run'] and keys['project_training_input'] and keys['project_training_version']
    accepted(client, prepared(client, auth))
    purge(owner)
    with Session(engine) as session:
        for table, captured in keys.items():
            if captured:
                assert session.execute(text(f'SELECT count(*) FROM "{table}" t WHERE account_row_key(:table,to_jsonb(t))=ANY(:keys)'), {'table':table, 'keys':list(captured)}).scalar_one() == 0, table
        assert session.get(User, other) is not None
    assert client.get(f'{path}/{identities[0]}', headers=auth).status_code == 401
    after = client.get(f'{path}/{identities[1]}', headers=other_auth)
    assert after.status_code == 200, after.text
    assert after.json() == before_read
    after_list = client.get(path, headers=other_auth)
    assert after_list.status_code == 200, after_list.text
    assert after_list.json() == before_list


def test_unconsumed_verification_and_reset_private_copies_are_erased(client):
    import hashlib
    import secrets
    from datetime import UTC, datetime, timedelta

    from app.models import EmailVerification, PasswordReset

    participants = [account(), account()]
    tokens = {}
    with Session(engine) as session:
        for owner, _ in participants:
            user = session.get(User, owner)
            now = datetime.now(UTC)
            for model in (EmailVerification, PasswordReset):
                token = secrets.token_urlsafe(32)
                tokens[(owner, model)] = token
                session.merge(model(user_id=owner, email=user.email, token_hash=hashlib.sha256(token.encode()).hexdigest(), expires_at=now+timedelta(hours=1), sent_at=now))
        session.commit()
        other = participants[1][0]
        kept = {model:session.get(model, other).model_dump() for model in (EmailVerification, PasswordReset)}
    owner, auth = participants[0]
    accepted(client, prepared(client, auth))
    purge(owner)
    with Session(engine) as session:
        for model in (EmailVerification, PasswordReset):
            assert session.get(model, owner) is None
            assert session.get(model, other).model_dump() == kept[model]
            assert not session.exec(select(model).where(model.token_hash == hashlib.sha256(tokens[(owner, model)].encode()).hexdigest())).all()


def test_real_guidance_receipts_and_both_draft_scopes_are_erased(client, tmp_path):
    from app.account_erasure.inventory import TABLES
    from tests import test_practices
    from tests.test_training import provider as provider_fixture

    supplier_fixture = provider_fixture.__wrapped__(tmp_path)
    supplier = next(supplier_fixture)
    ready_fixture = test_practices.ready.__wrapped__(tmp_path, supplier)
    ready = next(ready_fixture)
    try:
        test_practices.test_practice_draft_is_separate_and_original_lineage_unchanged(ready, supplier)
        auth, identity, *_ = ready
        owner = uuid.UUID(client.get('/api/v1/users/me', headers=auth).json()['id'])
        with Session(engine) as session:
            captured = {
                table: session.execute(text(f'SELECT account_row_key(:table,to_jsonb(t)) FROM "{table}" t WHERE account_row_owner(:table,to_jsonb(t))=:owner'), {'table':table, 'owner':owner}).scalars().all()
                for table in TABLES
            }
            for table in ('concept_help', 'help_delivery', 'practice_draft', 'training_draft', 'draft_collection'):
                assert captured[table], table
        accepted(client, prepared(client, auth))
        purge(owner)
        with Session(engine) as session:
            for table, keys in captured.items():
                if keys:
                    assert session.execute(text(f'SELECT count(*) FROM "{table}" t WHERE account_row_key(:table,to_jsonb(t))=ANY(:keys)'), {'table':table, 'keys':list(keys)}).scalar_one() == 0, table
        assert client.get(f'/api/v1/training/tasks/{identity}', headers=auth).status_code == 401
    finally:
        ready_fixture.close()
        supplier_fixture.close()
