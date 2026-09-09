import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlmodel import Session, select

from app.capabilities.catalog import CATALOG, EvidenceKey
from app.capabilities.evidence import CapabilityState, EvidenceMap
from app.capabilities.unlocks import OpenedUnit
from app.core.db import engine
from app.training.models import TrainingRun
from tests.test_accounts import client
from tests.test_model_config import account, save

BASE = EvidenceKey(
    capability_id="network.delivery",
    difficulty="基础",
    background_id="network-evidence-v1",
)
ADVANCED = BASE.model_copy(update={"difficulty": "进阶"})


def open_request(auth, target=ADVANCED):
    return client.post(
        "/api/v1/capabilities/open",
        headers=auth,
        json={"target": target.model_dump(), "catalog_version": CATALOG.version},
    )


def test_access_and_open_never_accept_self_report_or_other_background():
    owner, auth = account()
    assert client.get("/api/v1/capabilities/access").status_code == 401
    _, unverified = account(False)
    assert (
        client.get("/api/v1/capabilities/access", headers=unverified).status_code == 403
    )
    response = open_request(auth)
    assert response.status_code == 409 and response.json()["detail"]["access"][
        "missing_required"
    ] == [BASE.model_dump()]
    assert (
        client.post(
            "/api/v1/capabilities/open",
            headers=auth,
            json={
                "target": ADVANCED.model_dump(),
                "catalog_version": CATALOG.version,
                "verified": True,
            },
        ).status_code
        == 422
    )
    assert (
        open_request(
            auth, BASE.model_copy(update={"background_id": "other"})
        ).status_code
        == 422
    )
    with Session(engine) as session:
        assert not session.exec(
            select(OpenedUnit).where(OpenedUnit.user_id == owner)
        ).all()
    assert open_request(auth, BASE).status_code == 200
    with Session(engine) as session:
        assert not session.exec(
            select(TrainingRun).where(TrainingRun.user_id == owner)
        ).all()


def test_actual_open_transaction_concurrency_retention_and_restore(monkeypatch):
    from app.capabilities import unlocks

    owner, auth = account()
    evidence = EvidenceMap(states=[CapabilityState(target=BASE, status="verified")])
    monkeypatch.setattr(unlocks, "read_evidence", lambda *_: evidence)
    barrier = Barrier(2)

    def apply(_):
        barrier.wait(5)
        return open_request(auth)

    with ThreadPoolExecutor(2) as pool:
        assert [r.status_code for r in pool.map(apply, range(2))] == [200, 200]
    evidence.states[0].status = "needs_consolidation"
    assert open_request(auth).json()["opened"]
    _, other = account()
    assert open_request(other).status_code == 409
    evidence.states[0].status = "verified"
    assert open_request(other).status_code == 200
    with Session(engine) as session:
        assert (
            len(
                session.exec(
                    select(OpenedUnit).where(OpenedUnit.user_id == owner)
                ).all()
            )
            == 1
        )
    assert (
        client.get("/api/v1/capabilities/evidence", headers=auth).json()["states"] == []
    )


def test_target_rejection_config_and_idempotency_without_model():
    owner, auth = account()
    config = save(auth).json()
    body = {
        "target": ADVANCED.model_dump(),
        "catalog_version": CATALOG.version,
        "request_id": str(uuid.uuid4()),
        "expected_config_version": config["version"],
        "disclosure_accepted": True,
        "mode": "practice",
    }
    assert (
        client.post("/api/v1/capabilities/start", headers=auth, json=body).status_code
        == 409
    )
    body.update(target=BASE.model_dump(), return_target=ADVANCED.model_dump())
    result = client.post("/api/v1/capabilities/start", headers=auth, json=body)
    assert result.status_code == 202, result.text
    try:
        assert result.json()["return_target"] == ADVANCED.model_dump()
        assert (
            client.post("/api/v1/capabilities/start", headers=auth, json=body).json()[
                "id"
            ]
            == result.json()["id"]
        )
        _, other = account()
        assert (
            client.post(
                "/api/v1/capabilities/start", headers=other, json=body
            ).status_code
            == 409
        )
        assert (
            client.get("/api/v1/capabilities/evidence", headers=auth).json()["states"]
            == []
        )
    finally:
        client.post(f"/api/v1/training/tasks/{result.json()['id']}/stop", headers=auth)


@pytest.mark.parametrize("open_first", [True, False])
def test_open_and_evidence_change_are_serialized_by_actual_owner_lock(
    monkeypatch, open_first
):
    import time
    from threading import Event

    from sqlalchemy import text

    from app.capabilities import routes, unlocks
    from app.model_config.service import lock_owner

    owner, auth = account()
    evidence = EvidenceMap(states=[CapabilityState(target=BASE, status="verified")])
    monkeypatch.setattr(unlocks, "read_evidence", lambda *_: evidence)
    entered, release = Event(), Event()

    def held(session, user_id):
        lock_owner(session, user_id)
        if open_first:
            entered.set()
            assert release.wait(10)

    monkeypatch.setattr(routes, "lock_owner", held)

    def change():
        with Session(engine) as session:
            lock_owner(session, owner)
            if not open_first:
                entered.set()
                assert release.wait(10)
            evidence.states[0].status = "needs_consolidation"
            session.commit()

    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(open_request, auth) if open_first else pool.submit(change)
        assert entered.wait(5)
        second = pool.submit(change) if open_first else pool.submit(open_request, auth)
        try:
            deadline = time.monotonic() + 5
            while True:
                with Session(engine) as session:
                    blocked = session.execute(
                        text(
                            "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND query LIKE 'SELECT \"user\".%FOR UPDATE%'"
                        )
                    ).scalar()
                if blocked:
                    break
                assert time.monotonic() < deadline
                time.sleep(0.02)
            assert not second.done()
        finally:
            release.set()
        result = first.result(10) if open_first else second.result(10)
        assert result.status_code == (200 if open_first else 409)
        (second if open_first else first).result(10)
    with Session(engine) as session:
        assert (
            bool(
                session.exec(
                    select(OpenedUnit).where(OpenedUnit.user_id == owner)
                ).all()
            )
            == open_first
        )


def test_open_commit_failure_does_not_publish_success(monkeypatch):
    from fastapi import HTTPException

    from app.capabilities import routes

    owner, auth = account()
    real = routes.open_unit

    def fail(*args):
        real(*args)
        raise HTTPException(503, "controlled precommit failure")

    monkeypatch.setattr(routes, "open_unit", fail)
    assert open_request(auth, BASE).status_code == 503
    with Session(engine) as session:
        assert not session.exec(
            select(OpenedUnit).where(OpenedUnit.user_id == owner)
        ).all()
