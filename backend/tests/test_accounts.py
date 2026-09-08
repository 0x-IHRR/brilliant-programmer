import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.main import app
from app.models import Invitation, User

client = TestClient(app, client=(f"suite-{uuid.uuid4()}", 50000))
PASSWORD = "local-test-password-only"


def email():
    return f"test-{uuid.uuid4()}@example.com"


def login(address, password=PASSWORD):
    result = client.post(
        "/api/v1/login/access-token", data={"username": address, "password": password}
    )
    assert result.status_code == 200, result.text
    return {"Authorization": "Bearer " + result.json()["access_token"]}


def admin():
    return login(settings.FIRST_SUPERUSER, settings.FIRST_SUPERUSER_PASSWORD)


def invite():
    result = client.post("/api/v1/invitations", headers=admin())
    assert result.status_code == 201
    return result.json()


def signup(code, address=None, **extra):
    return client.post(
        "/api/v1/users/signup",
        json={
            "email": address or email(),
            "password": PASSWORD,
            "invitation_code": code,
            **extra,
        },
    )


def state(code):
    with Session(engine) as session:
        return (
            session.exec(select(Invitation).where(Invitation.code == code)).one().status
        )


def test_registration_boundary_and_no_privilege_bypass():
    invitation = invite()
    result = signup(
        invitation["code"], is_superuser=True, email_verified=True, level="管理员"
    )
    assert result.status_code == 201
    user = result.json()
    assert not user["email_verified"] and not user["is_superuser"]
    assert user["level"] == "小白程序员" and "hashed_password" not in user
    headers = login(user["email"])
    assert user.pop("verification_sent") in (True, False)
    assert client.get("/api/v1/users/me", headers=headers).json() == user
    assert client.get("/api/v1/training/access", headers=headers).status_code == 403
    for auth in [{}, headers]:
        assert client.post("/api/v1/invitations", headers=auth).status_code in (
            401,
            403,
        )
        assert client.get("/api/v1/invitations", headers=auth).status_code in (401, 403)
        assert client.post(
            f"/api/v1/invitations/{invitation['id']}/revoke", headers=auth
        ).status_code in (401, 403)
    assert signup(invitation["code"]).status_code == 409
    assert (
        client.post(
            f"/api/v1/invitations/{invitation['id']}/revoke", headers=admin()
        ).status_code
        == 409
    )
    assert state(invitation["code"]) == "used"
    assert (
        client.post(
            "/api/v1/users/",
            headers=admin(),
            json={"email": email(), "password": PASSWORD},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/v1/private/users/", json={"email": email(), "password": PASSWORD}
        ).status_code
        == 404
    )
    assert (
        client.patch(
            "/api/v1/users/me", headers=headers, json={"email": email()}
        ).status_code
        == 405
    )
    assert (
        client.post(
            "/api/v1/users/signup", json={"email": email(), "password": PASSWORD}
        ).status_code
        == 422
    )
    assert signup("invalid-code-long-enough").status_code == 409


def test_failed_registration_preserves_code_and_old_codes_work():
    invitation = invite()
    with Session(engine) as session:
        row = session.get(Invitation, uuid.UUID(invitation["id"]))
        row.created_at = datetime(2000, 1, 1, tzinfo=UTC)
        session.add(row)
        session.commit()
    assert (
        signup(invitation["code"], settings.FIRST_SUPERUSER.upper()).status_code == 409
    )
    assert state(invitation["code"]) == "unused"
    assert signup(invitation["code"], password="short").status_code == 422
    assert state(invitation["code"]) == "unused"
    assert signup(invitation["code"]).status_code == 201


def test_concurrent_registration_exactly_once():
    invitation = invite()
    barrier = Barrier(4)
    addresses = [email() for _ in range(4)]

    def run(address):
        barrier.wait()
        return signup(invitation["code"], address).status_code

    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(run, addresses))
    assert sorted(results) == [201, 409, 409, 409]
    with Session(engine) as session:
        assert (
            len(session.exec(select(User).where(User.email.in_(addresses))).all()) == 1
        )
    assert state(invitation["code"]) == "used"


def test_concurrent_revocation_and_signup():
    for _ in range(4):
        invitation = invite()
        headers = admin()
        barrier = Barrier(2)

        def register(barrier=barrier, invitation=invitation):
            barrier.wait()
            return signup(invitation["code"]).status_code

        def revoke(barrier=barrier, invitation=invitation, headers=headers):
            barrier.wait()
            return client.post(
                f"/api/v1/invitations/{invitation['id']}/revoke", headers=headers
            ).status_code

        with ThreadPoolExecutor(2) as pool:
            registration, revocation = pool.submit(register), pool.submit(revoke)
            r, v = registration.result(), revocation.result()
        assert (r, v, state(invitation["code"])) in [
            (201, 409, "used"),
            (409, 200, "revoked"),
        ]


def test_revoke_idempotent_and_wrong_credentials():
    invitation = invite()
    for _ in range(2):
        assert (
            client.post(
                f"/api/v1/invitations/{invitation['id']}/revoke", headers=admin()
            ).json()["status"]
            == "revoked"
        )
    assert signup(invitation["code"]).status_code == 409
    assert (
        client.get(
            "/api/v1/users/me", headers={"Authorization": "Bearer bad-token"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/login/access-token",
            data={"username": email(), "password": PASSWORD},
        ).status_code
        == 401
    )


def test_rate_limit_persists_between_requests():
    limited = TestClient(app, client=(f"limit-{uuid.uuid4()}", 50000))
    for _ in range(60):
        assert limited.post("/api/v1/login/access-token").status_code == 422
    response = limited.post("/api/v1/login/access-token")
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"
