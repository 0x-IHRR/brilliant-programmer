import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import httpx
import jwt
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.core.security import ALGORITHM
from app.main import app
from app.models import EmailVerification, Invitation, LoginSession, User

client = TestClient(app, client=(f"verify-{uuid.uuid4()}", 50001))
PASSWORD = "verification-test-password"
MAILPIT = os.environ.get("MAILPIT_URL", "http://127.0.0.1:18025")


def register():
    with Session(engine) as session:
        invite = Invitation(code=uuid.uuid4().hex)
        session.add(invite)
        session.commit()
        code = invite.code
    email = f"verify-{uuid.uuid4()}@example.com"
    response = client.post(
        "/api/v1/users/signup",
        json={
            "email": email,
            "password": PASSWORD,
            "invitation_code": code,
        },
    )
    assert response.status_code == 201, response.text
    with Session(engine) as session:
        assert (
            session.exec(select(Invitation).where(Invitation.code == code)).one().status
            == "used"
        )
    return response.json()


def login(user):
    response = client.post(
        "/api/v1/login/access-token",
        data={"username": user["email"], "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def received_token(user):
    # Actual SMTP delivery, queried only from the isolated local capture service.
    response = httpx.get(f"{MAILPIT}/api/v1/messages", params={"limit": 1000})
    response.raise_for_status()
    messages = response.json()["messages"]
    message = next(
        m for m in messages if any(t["Address"] == user["email"] for t in m["To"])
    )
    body = httpx.get(f"{MAILPIT}/api/v1/message/{message['ID']}").json()["Text"]
    assert PASSWORD not in body
    return re.search(r"#verify=([A-Za-z0-9_-]{43})", body)[1]


def age_link(user, expire=False):
    with Session(engine) as session:
        row = session.get(EmailVerification, uuid.UUID(user["id"]))
        row.sent_at = datetime.now(UTC) - timedelta(minutes=2)
        if expire:
            row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.add(row)
        session.commit()


def verify(headers, token):
    return client.post(
        "/api/v1/users/me/verify-email", headers=headers, json={"token": token}
    )


def test_smtp_verification_session_and_account_boundaries():
    user, other = register(), register()
    assert user["verification_sent"] is True
    token = received_token(user)
    auth, other_auth = login(user), login(other)
    assert client.get("/api/v1/training/access", headers=auth).status_code == 403
    assert verify({}, token).status_code == 401
    assert verify(other_auth, token).status_code == 400
    assert verify(auth, "x" * 43).status_code == 400
    assert verify(auth, "short").status_code == 422
    for path in (
        f"/api/v1/users/{other['id']}",
        f"/api/v1/users/{other['id']}/verify-email",
    ):
        assert client.get(path, headers=auth).status_code == 404
    verified = verify(auth, token)
    assert verified.status_code == 200
    assert verified.json()["id"] == user["id"]
    assert verified.json()["email_verified"] is True
    assert verified.json()["is_superuser"] is False
    assert verified.json()["level"] == "小白程序员"
    assert verify(auth, token).status_code == 400
    assert client.get("/api/v1/training/access", headers=auth).status_code == 200
    assert client.get("/api/v1/training/access", headers=other_auth).status_code == 403
    assert client.post("/api/v1/invitations", headers=auth).status_code == 403
    second_device = login(user)
    assert client.post("/api/v1/login/logout", headers=auth).status_code == 200
    for path in ("/api/v1/users/me", "/api/v1/training/access"):
        assert client.get(path, headers=auth).status_code == 401
    assert client.get("/api/v1/users/me", headers=second_device).status_code == 200
    assert client.post("/api/v1/login/logout", headers=auth).status_code == 401
    payload = jwt.decode(
        second_device["Authorization"][7:], settings.SECRET_KEY, algorithms=[ALGORITHM]
    )
    # Even a valid server signature must not bind another account to this session.
    payload["sub"] = other["id"]
    forged_binding = jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)
    assert (
        client.get(
            "/api/v1/users/me", headers={"Authorization": f"Bearer {forged_binding}"}
        ).status_code
        == 401
    )
    with Session(engine) as session:
        row = session.get(LoginSession, uuid.UUID(payload["jti"]))
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.add(row)
        session.commit()
    assert client.get("/api/v1/users/me", headers=second_device).status_code == 401


def test_expiry_resend_failure_and_concurrent_replay(monkeypatch):
    user = register()
    token = received_token(user)
    auth = login(user)
    assert (
        client.post("/api/v1/users/me/verification-email", headers=auth).status_code
        == 429
    )
    age_link(user)
    with ThreadPoolExecutor(2) as pool:
        statuses = list(
            pool.map(
                lambda _: (
                    client.post(
                        "/api/v1/users/me/verification-email", headers=auth
                    ).status_code
                ),
                range(2),
            )
        )
    assert sorted(statuses) == [200, 429]
    token = received_token(user)
    age_link(user, expire=True)
    assert verify(auth, token).status_code == 400
    assert (
        client.post("/api/v1/users/me/verification-email", headers=auth).status_code
        == 200
    )
    replacement = received_token(user)
    assert replacement != token
    assert verify(auth, token).status_code == 400
    age_link(user)

    def failed_smtp(*_args, **_kwargs):
        raise OSError("synthetic SMTP failure")

    with monkeypatch.context() as patch:
        patch.setattr("app.core.verification.smtplib.SMTP", failed_smtp)
        assert (
            client.post("/api/v1/users/me/verification-email", headers=auth).status_code
            == 503
        )
    # Failed resend retains the earlier unexpired link; concurrent use succeeds once.
    with ThreadPoolExecutor(2) as pool:
        statuses = list(
            pool.map(lambda _: verify(auth, replacement).status_code, range(2))
        )
    assert sorted(statuses) == [200, 400]
    assert (
        client.post("/api/v1/users/me/verification-email", headers=auth).status_code
        == 200
    )


def test_initial_send_failure_keeps_account_and_can_recover(monkeypatch):
    def failed_smtp(*_args, **_kwargs):
        raise OSError("synthetic SMTP failure")

    with monkeypatch.context() as patch:
        patch.setattr("app.core.verification.smtplib.SMTP", failed_smtp)
        user = register()
    assert user["verification_sent"] is False
    assert user["email_verified"] is False
    auth = login(user)
    assert client.get("/api/v1/training/access", headers=auth).status_code == 403
    assert (
        client.post("/api/v1/users/me/verification-email", headers=auth).status_code
        == 200
    )
    assert verify(auth, received_token(user)).status_code == 200


def test_email_binding_and_inactive_account():
    user = register()
    token = received_token(user)
    auth = login(user)
    with Session(engine) as session:
        row = session.get(User, uuid.UUID(user["id"]))
        row.email = f"changed-{uuid.uuid4()}@example.com"
        session.add(row)
        session.commit()
    assert verify(auth, token).status_code == 400
    with Session(engine) as session:
        row = session.get(User, uuid.UUID(user["id"]))
        row.is_active = False
        session.add(row)
        session.commit()
    assert client.get("/api/v1/users/me", headers=auth).status_code == 401
