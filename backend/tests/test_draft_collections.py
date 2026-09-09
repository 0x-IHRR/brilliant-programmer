import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlmodel import Session

from app.core.db import engine
from app.training.models import TrainingRun
from tests.test_accounts import client
from tests.test_draft_api import draft, url
from tests.test_model_config import account
from tests.test_submissions import payload
from tests.test_submissions import provider as submission_provider
from tests.test_submissions import ready as submission_ready

provider = submission_provider
ready = submission_ready


def read(auth, path):
    response = client.get(path + "/versions", headers=auth)
    assert response.status_code == 200, response.text
    return response.json()


def write(state, text="输入", expected=None):
    return {
        **draft(expected, answers=[{"judgment_id": "j1", "value": 1, "reason": text}]),
        "observed_revision": state["revision"],
        "generation": state["generation"],
    }


def test_three_devices_preserve_select_delete_and_block_submit(ready, provider):
    _, auth, run_id, config, *_ = ready
    path = url(run_id)
    original = read(auth, path)
    a, b, c = [write(original, text) for text in ["A依据", "B依据", "C依据"]]
    assert client.put(path, headers=auth, json=a).status_code == 200
    assert client.put(path, headers=auth, json=b).status_code == 409
    assert client.put(path, headers=auth, json=c).status_code == 409
    state = read(auth, path)
    assert len(state["unresolved"]) == 3
    assert [v["progress"]["answers"][0]["reason"] for v in state["versions"]] == [
        "A依据",
        "B依据",
        "C依据",
    ]
    assert (
        client.post(
            path.removesuffix("/draft") + "/submissions",
            headers=auth,
            json=payload(config),
        ).status_code
        == 409
    )
    chosen_id = state["versions"][1]["version"]
    chosen = client.post(
        path + "/choose",
        headers=auth,
        json={"observed_revision": state["revision"], "version": chosen_id},
    )
    assert chosen.status_code == 200 and not chosen.json()["unresolved"]
    assert len(chosen.json()["versions"]) == 3
    assert client.get(path, headers=auth).json()["progress"] == b["progress"]
    deleted = client.request(
        "DELETE",
        path,
        headers=auth,
        json={"observed_revision": chosen.json()["revision"], "version": chosen_id},
    )
    assert deleted.status_code == 200
    assert len(deleted.json()["versions"]) == 2
    assert client.get(path, headers=auth).json() is None
    assert client.put(path, headers=auth, json=a).status_code == 409
    assert (
        client.put(
            path, headers=auth, json=write(original, "第一次尚未保存")
        ).status_code
        == 409
    )
    assert client.put(path, headers=auth, json=draft()).status_code == 422
    with Session(engine) as session:
        run = session.get(TrainingRun, uuid.UUID(run_id))
        assert run.formal_submitted_at is None and run.event_sequence == 0
    assert len(provider["requests"]) == 1


def test_simultaneous_writes_keep_three_and_stale_choice_cannot_hide_new_input(ready):
    _, auth, run_id, *_ = ready
    path = url(run_id)
    state = read(auth, path)
    bodies = [write(state, text) for text in ["一", "二", "三"]]
    barrier = Barrier(3)

    def save(body):
        barrier.wait(5)
        return client.put(path, headers=auth, json=body)

    with ThreadPoolExecutor(3) as pool:
        results = list(pool.map(save, bodies))
    assert sorted(r.status_code for r in results) == [200, 409, 409]
    seen = read(auth, path)
    assert len(seen["versions"]) == 3
    assert client.put(path, headers=auth, json=write(state, "四")).status_code == 409
    stale = client.post(
        path + "/choose",
        headers=auth,
        json={"observed_revision": seen["revision"], "version": seen["current"]},
    )
    assert stale.status_code == 409
    assert len(read(auth, path)["unresolved"]) == 4


def test_collection_owner_and_commit_failure_do_not_claim_saved(ready, monkeypatch):
    from app.training import draft_collection

    _, auth, run_id, *_ = ready
    path = url(run_id)
    before = read(auth, path)
    _, other = account()
    for method, suffix, body in [
        ("GET", "/versions", None),
        (
            "POST",
            "/choose",
            {"observed_revision": before["revision"], "version": str(uuid.uuid4())},
        ),
        (
            "DELETE",
            "",
            {"observed_revision": before["revision"], "version": str(uuid.uuid4())},
        ),
    ]:
        assert (
            client.request(method, path + suffix, headers=other, json=body).status_code
            == 404
        )
    original = draft_collection.store

    def fail(session, state):
        original(session, state)
        from fastapi import HTTPException

        raise HTTPException(503, "controlled before commit")

    monkeypatch.setattr(draft_collection, "store", fail)
    assert client.put(path, headers=auth, json=write(before)).status_code == 503
    monkeypatch.setattr(draft_collection, "store", original)
    assert read(auth, path) == before


@pytest.mark.parametrize("operation", ["choose", "delete"])
@pytest.mark.parametrize("mutation_first", [True, False])
def test_actual_lock_orders_selection_deletion_and_old_write(
    ready, monkeypatch, operation, mutation_first
):
    import time
    from threading import Event

    from sqlalchemy import text

    from app.training import drafts

    _, auth, run_id, *_ = ready
    path = url(run_id)
    initial = read(auth, path)
    first = client.put(path, headers=auth, json=write(initial, "现有内容"))
    assert first.status_code == 200
    observed = read(auth, path)
    stale_write = write(observed, "仍在旧设备编辑", observed["current"])
    mutation_body = {
        "observed_revision": observed["revision"],
        "version": observed["current"],
    }
    entered, release = Event(), Event()
    original_lock = drafts.lock_owner
    calls = []

    def held(session, owner):
        result = original_lock(session, owner)
        calls.append(1)
        if len(calls) == 1:
            entered.set()
            assert release.wait(10)
        return result

    monkeypatch.setattr(drafts, "lock_owner", held)

    def mutation():
        return (
            client.post(path + "/choose", headers=auth, json=mutation_body)
            if operation == "choose"
            else client.request("DELETE", path, headers=auth, json=mutation_body)
        )

    def save():
        return client.put(path, headers=auth, json=stale_write)

    with ThreadPoolExecutor(2) as pool:
        leader = pool.submit(mutation if mutation_first else save)
        try:
            assert entered.wait(5)
            follower = pool.submit(save if mutation_first else mutation)
            deadline = time.monotonic() + 5
            while True:
                with Session(engine) as session:
                    waiting = session.execute(
                        text(
                            "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND query LIKE 'SELECT \"user\".%FOR UPDATE%' "
                        )
                    ).scalar()
                if waiting:
                    break
                assert time.monotonic() < deadline
                time.sleep(0.02)
            assert not follower.done()
        finally:
            release.set()
        assert leader.result(10).status_code == 200
        assert follower.result(10).status_code == 409
    after = read(auth, path)
    if mutation_first and operation == "delete":
        assert after["versions"] == [] and after["current"] is None
    elif mutation_first:
        assert len(after["versions"]) == 2 and len(after["unresolved"]) == 2
    else:
        assert len(after["versions"]) == 2 and after["current"] != observed["current"]
