import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, select

from app.api.routes import accounts
from app.core.db import engine
from app.core.security import get_password_hash
from app.core.verification import token_hash
from app.main import app
from app.model_config.models import ModelConfig
from app.models import LoginSession, PasswordReset, User

PASSWORD = "old-reset-test-password"
NEW = "new-reset-test-password"
MAILPIT = os.environ.get("MAILPIT_URL", "http://127.0.0.1:18025")


def client():
    return TestClient(app, client=(f"reset-{uuid.uuid4()}", 50004))


def user(verified=True):
    with Session(engine) as session:
        row = User(email=f"reset-{uuid.uuid4()}@example.com", hashed_password=get_password_hash(PASSWORD), email_verified=verified)
        session.add(row)
        session.commit()
        session.refresh(row)
        return row


def login(c, u, password=PASSWORD):
    return c.post("/api/v1/login/access-token", data={"username": u.email, "password": password})


def auth(response):
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def request(c, u):
    return c.post("/api/v1/password-reset/request", json={"email": u.email.upper()})


def received(u):
    messages = httpx.get(f"{MAILPIT}/api/v1/messages", params={"limit": 1000}).json()["messages"]
    message = next(m for m in messages if any(t["Address"] == u.email for t in m["To"]))
    body = httpx.get(f"{MAILPIT}/api/v1/message/{message['ID']}").json()["Text"]
    assert PASSWORD not in body and NEW not in body
    return re.search(r"#reset=([A-Za-z0-9_-]{43})", body)[1]


def reset(c, token, password=NEW):
    return c.post("/api/v1/password-reset/confirm", json={"token": token, "password": password})


def age(u, expire=False):
    with Session(engine) as session:
        row = session.get(PasswordReset, u.id)
        row.sent_at -= timedelta(minutes=2)
        if expire:
            row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.add(row)
        session.commit()


def test_reset_two_devices_preserves_account_and_model_config():
    c, u, other = client(), user(), user()
    a, b, other_auth = auth(login(c, u)), auth(login(c, u)), auth(login(c, other))
    config = c.put("/api/v1/model-config", headers=a, json={"service_url": "https://api.example.com/v1", "model_id": "synthetic", "api_key": "synthetic-key", "expected_version": None, "disclosure_accepted": True})
    assert config.status_code == 200
    with Session(engine) as session:
        original = session.get(ModelConfig, u.id).model_dump()
    assert request(c, u).status_code == 202
    token = received(u)
    with Session(engine) as session:
        assert session.get(PasswordReset, u.id).token_hash == token_hash(token)
    for invalid, password, status in [("x" * 43, NEW, 400), (token, "short", 422), ("short", NEW, 422)]:
        response = reset(c, invalid, password)
        assert response.status_code == status
        assert NEW not in response.text and token not in response.text
    for headers in (a, b):
        assert c.get("/api/v1/users/me", headers=headers).status_code == 200
    assert reset(c, token).status_code == 200
    assert reset(c, token).status_code == 400
    for headers in (a, b):
        for path in ("/api/v1/users/me", "/api/v1/training/access", "/api/v1/model-config", "/api/v1/capabilities/catalog"):
            response = c.get(path, headers=headers)
            assert response.status_code == 401 and "重新登录" in response.text
    assert login(c, u).status_code == 401
    assert c.get("/api/v1/users/me", headers=auth(login(c, u, NEW))).json()["level"] == u.level
    assert c.get("/api/v1/users/me", headers=other_auth).status_code == 200
    with Session(engine) as session:
        assert session.get(ModelConfig, u.id).model_dump() == original
        assert session.get(User, u.id).email_verified
        assert session.get(PasswordReset, u.id) is None


def test_generic_response_and_request_protection(monkeypatch):
    c, u, unverified = client(), user(), user(False)
    responses = [request(c, x) for x in (u, unverified, User(email=f"unknown-{uuid.uuid4()}@example.com", hashed_password="unused"), u)]
    assert all(r.status_code == 202 and r.json() == responses[0].json() for r in responses)
    with Session(engine) as session:
        assert session.get(PasswordReset, unverified.id) is None
    token = received(u)
    assert request(c, u).status_code == 202 and received(u) == token
    age(u)
    def fail(*_args, **_kwargs):
        raise OSError("synthetic failure")
    monkeypatch.setattr("app.core.verification.smtplib.SMTP", fail)
    assert request(c, u).json() == responses[0].json()
    assert reset(c, token).status_code == 200
    limited = client()
    for _ in range(60):
        assert request(limited, unverified).status_code == 202
    response = request(limited, unverified)
    assert response.status_code == 429 and response.headers["Retry-After"] == "60"


def test_expiry_resend_and_concurrent_one_use():
    c, u = client(), user()
    request(c, u)
    old = received(u)
    age(u, expire=True)
    assert reset(c, old).status_code == 400
    request(c, u)
    replacement = received(u)
    assert replacement != old and reset(c, old).status_code == 400
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: reset(c, replacement).status_code, range(2)))
    assert sorted(results) == [200, 400]


@pytest.mark.parametrize("field,value", [("email_verified", False), ("is_active", False), ("email", "changed@example.com")])
def test_changed_account_rejects_reset(field, value):
    c, u = client(), user()
    request(c, u)
    token = received(u)
    with Session(engine) as session:
        row = session.get(User, u.id)
        setattr(row, field, value if field != "email" else f"{uuid.uuid4()}-{value}")
        session.add(row)
        session.commit()
    assert reset(c, token).status_code == 400


def wait_for_lock():
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with engine.connect() as connection:
            waiting = connection.execute(text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock' AND query LIKE '%FOR UPDATE%'")).scalar_one()
        if waiting:
            return
        time.sleep(0.01)
    pytest.fail("concurrent request did not reach the PostgreSQL user lock")


def test_login_holding_old_password_cannot_outlive_reset(monkeypatch):
    c, u = client(), user()
    request(c, u)
    token = received(u)
    entered, release = threading.Event(), threading.Event()
    original = accounts.verify_password
    def paused(*args):
        result = original(*args)
        entered.set()
        assert release.wait(10)
        return result
    monkeypatch.setattr(accounts, "verify_password", paused)
    with ThreadPoolExecutor(2) as pool:
        logging_in = pool.submit(login, c, u)
        assert entered.wait(5)
        resetting = pool.submit(reset, c, token)
        try:
            wait_for_lock()
        finally:
            release.set()
        old_session = auth(logging_in.result(timeout=10))
        assert resetting.result(timeout=10).status_code == 200
    assert c.get("/api/v1/users/me", headers=old_session).status_code == 401


def test_login_waiting_for_reset_reads_new_hash_and_cached_orm_refreshes(monkeypatch):
    c, u = client(), user()
    request(c, u)
    token = received(u)
    entered, release = threading.Event(), threading.Event()
    original = accounts.get_password_hash
    def paused(password):
        entered.set()
        assert release.wait(10)
        return original(password)
    monkeypatch.setattr(accounts, "get_password_hash", paused)
    with Session(engine) as cached:
        stale = cached.get(User, u.id)
        with ThreadPoolExecutor(2) as pool:
            resetting = pool.submit(reset, c, token)
            assert entered.wait(5)
            logging_in = pool.submit(login, c, u)
            try:
                wait_for_lock()
            finally:
                release.set()
            assert resetting.result(timeout=10).status_code == 200
            assert logging_in.result(timeout=10).status_code == 401
        assert stale.hashed_password == u.hashed_password
        with pytest.raises(HTTPException) as error:
            accounts.login(cached, OAuth2PasswordRequestForm(username=u.email, password=PASSWORD))
        assert error.value.status_code == 401
    with Session(engine) as session:
        assert not session.exec(select(LoginSession).where(LoginSession.user_id == u.id)).all()


def test_live_resend_and_failed_transaction_preserve_credentials(monkeypatch):
    c, u = client(), user()
    headers = auth(login(c, u))
    request(c, u)
    old = received(u)
    age(u)
    request(c, u)
    fresh = received(u)
    assert fresh != old and reset(c, old).status_code == 400
    def failed_commit(session):
        session.flush()
        raise RuntimeError("synthetic failure after database writes")
    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", failed_commit)
        with pytest.raises(RuntimeError, match="synthetic failure"):
            reset(c, fresh)
    assert c.get("/api/v1/users/me", headers=headers).status_code == 200
    assert login(c, u).status_code == 200
    assert reset(c, fresh).status_code == 200


def test_rejects_replacement_identity_and_redacts_bad_payloads():
    c = client()
    for path, body in [
        ("request", {"email": "someone@example.com", "recipient": "attacker@example.com"}),
        ("confirm", {"token": "x" * 43, "password": NEW, "user_id": str(uuid.uuid4())}),
        ("confirm", {"token": "x" * 43, "password": "p" * 129}),
    ]:
        response = c.post(f"/api/v1/password-reset/{path}", json=body)
        assert response.status_code == 422
        assert NEW not in response.text and "attacker" not in response.text
    response = c.post("/api/v1/password-reset/confirm", content='{"password":"synthetic-secret",', headers={"Content-Type": "application/json"})
    assert response.status_code == 422 and "synthetic-secret" not in response.text
