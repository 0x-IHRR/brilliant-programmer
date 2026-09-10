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
