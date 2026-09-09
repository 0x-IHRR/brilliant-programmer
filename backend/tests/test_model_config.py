import base64
import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from fastapi import HTTPException
from pydantic import SecretStr
from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.core.security import get_password_hash
from app.model_config.models import ModelConfig
from app.model_config.service import credential_for_call, decrypt
from app.models import User
from tests.test_accounts import client, login

URL = "/api/v1/model-config"
FAKE_KEY = "fake-only-key-never-a-real-provider-secret"


def account(verified=True):
    with Session(engine) as session:
        user = User(
            email=f"config-{uuid.uuid4()}@example.com",
            email_verified=verified,
            hashed_password=get_password_hash("local-test-password-only"),
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user.id, login(user.email)


def body(**changes):
    return {
        "service_url": "https://api.example.com/v1",
        "model_id": "fake-model",
        "api_key": FAKE_KEY,
        "disclosure_accepted": True,
        **changes,
    }


def save(auth, **changes):
    return client.put(URL, headers=auth, json=body(**changes))


def test_lifecycle_is_encrypted_persistent_owned_and_revoked(monkeypatch, caplog):
    owner, auth = account()
    other, other_auth = account()
    # No network or DNS should be needed to save: outbound clients fail if used.
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("unexpected DNS")),
    )
    assert client.get(URL, headers=auth).json() is None
    assert client.get(URL).status_code == 401
    result = save(auth)
    assert result.status_code == 200, result.text
    current = result.json()
    version = uuid.UUID(current["version"])
    assert set(current) == {"version", "service_url", "model_id", "has_key", "revoked", "quality"}
    assert FAKE_KEY not in result.text
    assert client.get(URL, headers=auth).headers["cache-control"] == "no-store"
    with Session(engine) as session:
        row = session.get(ModelConfig, owner)
        assert FAKE_KEY.encode() not in row.encrypted_key
        assert row.key_version == settings.MODEL_ACTIVE_KEY_VERSION
        assert decrypt(row).get_secret_value() == FAKE_KEY
        assert FAKE_KEY not in repr(row)
    # Independent fresh interpreter reads the DB and decrypts; no inherited memory.
    code = """import sys,uuid
from sqlmodel import Session
from app.core.db import engine
from app.model_config.models import ModelConfig
from app.model_config.service import decrypt
with Session(engine) as s:
 c=s.get(ModelConfig,uuid.UUID(sys.argv[1])); assert decrypt(c).get_secret_value()==sys.argv[2]
"""
    # Only a synthetic credential appears in test process arguments.
    assert (
        subprocess.run(
            [sys.executable, "-c", code, str(owner), FAKE_KEY], capture_output=True
        ).returncode
        == 0
    )
    assert client.get(URL, headers=other_auth).json() is None
    assert save(other_auth, expected_version=str(version)).status_code == 409
    for method in (client.get, client.put, client.delete):
        assert method(URL + "/" + str(owner), headers=other_auth).status_code == 404
    with Session(engine) as session, pytest.raises(HTTPException) as error:
        with credential_for_call(session, other, version):
            pytest.fail("cross-owner call")
    assert error.value.status_code == 409
    # Retain Key only on same destination, and changing model revokes old version.
    assert (
        save(
            auth,
            expected_version=str(version),
            api_key=None,
            service_url="https://other.example.com",
        ).status_code
        == 422
    )
    replaced = save(
        auth, expected_version=str(version), api_key=None, model_id="model-two"
    )
    assert replaced.status_code == 200
    second = replaced.json()["version"]
    with Session(engine) as session, pytest.raises(HTTPException):
        with credential_for_call(session, owner, version):
            pytest.fail("revoked call")
    assert save(auth, expected_version=str(version)).status_code == 409
    assert (
        client.delete(
            URL, headers=auth, params={"expected_version": str(version)}
        ).status_code
        == 409
    )
    replacement = save(auth, expected_version=second, api_key="fake-replacement")
    assert replacement.status_code == 200
    third = replacement.json()["version"]
    with Session(engine) as session:
        with credential_for_call(session, owner, uuid.UUID(third)) as (_, key):
            assert key.get_secret_value() == "fake-replacement"
    assert (
        client.delete(URL, headers=auth, params={"expected_version": third}).status_code
        == 204
    )
    assert (
        client.delete(URL, headers=auth, params={"expected_version": third}).status_code
        == 204
    )
    assert client.get(URL, headers=auth).json() is None
    with Session(engine) as session, pytest.raises(HTTPException):
        with credential_for_call(session, owner, uuid.UUID(third)):
            pytest.fail("deleted call")
    assert save(auth).status_code == 200  # Recreate cannot revive an old UUID.
    assert FAKE_KEY not in caplog.text


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.com",
        "https://localhost",
        "https://127.0.0.1/v1",
        "https://[::1]",
        "https://169.254.169.254",
        "https://api.example.com?key=secret",
        "https://a:b@api.example.com",
        "https://api.example.com/#secret",
        "https://api.example.com:0",
        "https://api.example.com:65536",
        "https://api.example.com:invalid",
        "https://api.example.com\\@127.0.0.1",
        "https://foo.internal",
        "https://api..example.com",
        "https://api.example.com\n",
    ],
)
def test_local_url_validation(url):
    from app.model_config.models import validate_service_url

    with pytest.raises(ValueError):
        validate_service_url(url)


def test_invalid_body_does_not_echo_secrets_and_unverified_cannot_configure(caplog):
    _, unverified = account(False)
    for method in (client.get, client.put, client.delete):
        assert method(URL, headers=unverified).status_code == 403
    owner, auth = account()
    for payload in [
        body(api_key={"raw": FAKE_KEY}),
        body(api_key="bad key " + FAKE_KEY),
        body(api_key=FAKE_KEY * 200),
        body(user_id=str(uuid.uuid4())),
        body(service_url="bad" + FAKE_KEY),
        body(model_id=" "),
        body(disclosure_accepted=False),
    ]:
        response = client.put(URL, headers=auth, json=payload)
        assert response.status_code == 422
        assert FAKE_KEY not in response.text
    response = client.put(
        URL,
        headers={**auth, "content-type": "application/json"},
        content='{"api_key":"' + FAKE_KEY,
    )
    assert response.status_code == 422 and FAKE_KEY not in response.text
    assert save(auth, api_key=None).status_code == 422
    with Session(engine) as session:
        assert session.get(ModelConfig, owner) is None
    assert FAKE_KEY not in caplog.text


def test_missing_material_tamper_and_rotation_fail_closed(monkeypatch):
    owner, auth = account()
    original = dict(settings.MODEL_ENCRYPTION_KEYS)
    monkeypatch.setattr(settings, "MODEL_ENCRYPTION_KEYS", {})
    assert save(auth).status_code == 503
    assert client.get(URL, headers=auth).json() is None
    monkeypatch.setattr(settings, "MODEL_ENCRYPTION_KEYS", original)
    first = save(auth).json()
    with Session(engine) as session:
        row = session.get(ModelConfig, owner)
        encrypted = row.encrypted_key
        row.encrypted_key = encrypted[:-1] + bytes([encrypted[-1] ^ 1])
        with pytest.raises(HTTPException):
            decrypt(row)
        row.encrypted_key = encrypted
        row.user_id = uuid.uuid4()
        with pytest.raises(HTTPException):
            decrypt(row)
    monkeypatch.setattr(settings, "MODEL_ENCRYPTION_KEYS", {})
    assert (
        save(auth, expected_version=first["version"], api_key=None).status_code == 503
    )
    assert client.get(URL, headers=auth).json()["version"] == first["version"]
    rotated = {**original, "v2": SecretStr(base64.b64encode(os.urandom(32)).decode())}
    monkeypatch.setattr(settings, "MODEL_ENCRYPTION_KEYS", rotated)
    monkeypatch.setattr(settings, "MODEL_ACTIVE_KEY_VERSION", "v2")
    response = save(auth, expected_version=first["version"], api_key=None)
    assert response.status_code == 200
    monkeypatch.setattr(settings, "MODEL_ENCRYPTION_KEYS", {"v2": rotated["v2"]})
    with Session(engine) as session:
        row = session.get(ModelConfig, owner)
        assert row.key_version == "v2" and decrypt(row).get_secret_value() == FAKE_KEY


def test_concurrent_save_and_delete_have_one_winner():
    owner, auth = account()
    first = save(auth).json()
    barrier = Barrier(2)

    def update():
        barrier.wait()
        return save(auth, expected_version=first["version"]).status_code

    def delete():
        barrier.wait()
        return client.delete(
            URL, headers=auth, params={"expected_version": first["version"]}
        ).status_code

    with ThreadPoolExecutor(2) as pool:
        a, b = pool.submit(update), pool.submit(delete)
        results = (a.result(), b.result())
    assert results in [(200, 409), (409, 204)]
    with Session(engine) as session:
        assert (
            len(
                session.exec(
                    select(ModelConfig).where(ModelConfig.user_id == owner)
                ).all()
            )
            <= 1
        )


def test_call_lock_orders_revocation():
    owner, auth = account()
    first = save(auth).json()
    acquired, release, deleting = Event(), Event(), Event()

    def call():
        with Session(engine) as session:
            with credential_for_call(session, owner, uuid.UUID(first["version"])):
                acquired.set()
                assert release.wait(5)

    def delete():
        deleting.set()
        return client.delete(
            URL, headers=auth, params={"expected_version": first["version"]}
        ).status_code

    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(call)
        assert acquired.wait(5)
        b = pool.submit(delete)
        assert deleting.wait(5)
        assert not b.done()
        release.set()
        a.result()
        assert b.result() == 204
    with Session(engine) as session, pytest.raises(HTTPException):
        with credential_for_call(session, owner, uuid.UUID(first["version"])):
            pytest.fail("new call after deletion")


@pytest.mark.parametrize("port", [1, 443, 8443, 65535])
def test_https_custom_ports_are_valid(port):
    from app.model_config.models import validate_service_url

    url = f"https://api.example.com:{port}/v1"
    assert validate_service_url(url) == url


def test_call_gate_refreshes_previously_loaded_disabled_user():
    owner, auth = account()
    version = uuid.UUID(save(auth).json()["version"])
    with Session(engine) as calling:
        cached = calling.get(User, owner)
        assert cached.is_active
        with Session(engine) as disabling:
            user = disabling.get(User, owner)
            user.is_active = False
            disabling.add(user)
            disabling.commit()
        assert cached.is_active  # The identity map still has the pre-disable value.
        with pytest.raises(HTTPException) as error:
            with credential_for_call(calling, owner, version):
                pytest.fail("disabled cached user must not receive credentials")
        assert error.value.status_code == 403
        assert not cached.is_active
