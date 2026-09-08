import uuid
from graphlib import CycleError

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlmodel import Session

from app.capabilities.catalog import CATALOG, Catalog, EvidenceKey
from app.core.db import engine
from app.core.security import get_password_hash
from app.main import app
from app.models import User


def test_authenticated_catalog_is_read_only_and_never_self_certifies():
    client = TestClient(app, client=(f"catalog-{uuid.uuid4()}", 50000))
    path = "/api/v1/capabilities/catalog"
    assert client.get(path).status_code == 401
    password = "catalog-test-password-only"
    with Session(engine) as session:
        user = User(
            email=f"catalog-{uuid.uuid4()}@example.com",
            hashed_password=get_password_hash(password),
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        user_id, email = user.id, user.email
    response = client.post(
        "/api/v1/login/access-token", data={"username": email, "password": password}
    )
    headers = {"Authorization": "Bearer " + response.json()["access_token"]}
    assert client.get(path, headers=headers).status_code == 403
    with Session(engine) as session:
        user = session.get(User, user_id)
        user.email_verified = True
        session.add(user)
        session.commit()
    before = client.get("/api/v1/users/me", headers=headers).json()
    result = client.get(path, headers=headers)
    assert result.status_code == 200
    assert result.headers["Cache-Control"] == "no-store"
    assert result.json() == CATALOG.model_dump(mode="json")
    assert len(result.json()["domains"]) == 14
    assert (
        client.post(
            path, headers=headers, json={"verified": True, "difficulty": "综合"}
        ).status_code
        == 405
    )
    assert (
        client.put(path, headers=headers, json={"level": "传奇程序员"}).status_code
        == 405
    )
    assert (
        client.get(path + "?verified=true&difficulty=综合", headers=headers).json()
        == result.json()
    )
    assert client.get("/api/v1/users/me", headers=headers).json() == before
    client.post("/api/v1/login/logout", headers=headers)
    assert client.get(path, headers=headers).status_code == 401


def test_all_domains_have_entry_routes_and_explicit_all_plus_any_semantics():
    for domain in CATALOG.domains:
        assert {example.difficulty for example in domain.examples} == {
            "基础",
            "进阶",
            "综合",
        }
        assert all(
            example.task != example.acceptable != example.insufficient
            for example in domain.examples
        )
        for capability in domain.capabilities:
            assert capability.criterion
            assert capability.levels[0].satisfied_by(set())
            assert not capability.levels[1].satisfied_by(set())
    # Architecture requires ALL explicit items AND one item from EACH alternative
    # group. This is a prerequisite calculation, not an accepted user self-report.
    capability = next(
        c
        for d in CATALOG.domains
        for c in d.capabilities
        if c.id == "architecture.evolution"
    )
    level = capability.levels[2]
    required = set(level.required)
    assert not level.satisfied_by(required)
    assert not level.satisfied_by(required | {level.alternatives[0][0]})
    for first in level.alternatives[0]:
        for second in level.alternatives[1]:
            assert level.satisfied_by(required | {first, second})
            assert not level.satisfied_by({first, second})
    valid = required | {group[0] for group in level.alternatives}
    original = level.required[0]
    for change in [
        {"difficulty": "基础"},
        {"background_id": "some-other-framework"},
        {"capability_id": "other.capability"},
    ]:
        wrong = EvidenceKey.model_validate(original.model_dump() | change)
        assert not level.satisfied_by((valid - {original}) | {wrong})


@pytest.mark.parametrize(
    "failure",
    [
        "cycle",
        "empty_group",
        "unknown_background",
        "unknown_capability",
        "duplicate",
        "missing_tier",
    ],
)
def test_bad_release_catalog_fails_closed(failure):
    data = CATALOG.model_dump(mode="json")
    capability = data["domains"][0]["capabilities"][0]
    level = capability["levels"][0]
    reference = {
        "capability_id": capability["id"],
        "difficulty": "基础",
        "background_id": capability["background_id"],
    }
    if failure == "cycle":
        level["required"] = [reference]
    elif failure == "empty_group":
        level["alternatives"] = [[]]
    elif failure == "unknown_background":
        level["required"] = [reference | {"background_id": "unregistered-framework"}]
    elif failure == "unknown_capability":
        level["required"] = [reference | {"capability_id": "missing.capability"}]
    elif failure == "duplicate":
        data["domains"][0]["capabilities"].append(capability)
    else:
        capability["levels"].pop()
    with pytest.raises((ValidationError, CycleError)):
        Catalog.model_validate(data)
