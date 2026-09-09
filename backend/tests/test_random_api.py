"""Real owner routes, PostgreSQL and a separate TLS model worker."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlmodel import Session, select

from app.core.db import engine
from app.training.models import TrainingRun
from app.training.preference_models import RandomPreference
from tests import test_submissions, test_training
from tests.test_accounts import client
from tests.test_model_config import account

provider = test_training.provider
ready = test_submissions.ready
PREFERENCE = "/api/v1/training/random-preference"


def pref(auth):
    response = client.get(PREFERENCE, headers=auth)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def change(auth, old, mode):
    return client.put(
        PREFERENCE,
        headers=auth,
        json={"expected_version": old["version"], "mode": mode},
    )


def start(auth, config, preference, **changes):
    body = {
        "request_id": str(uuid.uuid4()),
        "disclosure_accepted": True,
        "expected_config_version": config["version"],
        "expected_preference_version": preference["version"],
        **changes,
    }
    return client.post("/api/v1/training/random", headers=auth, json=body), body


def formal(ready):
    _, auth, identity, config, *_ = ready
    response = client.post(
        test_submissions.url(identity),
        headers=auth,
        json=test_submissions.payload(config),
    )
    assert response.status_code == 202, response.text
    assert test_submissions.wait_submission(auth, identity)["awarded_points"] == 10
    assert pref(auth)["has_record"]


def test_first_draft_and_failed_generation_never_create_formal_preference(
    ready, provider
):
    owner, auth, identity, config, *_ = ready
    assert pref(auth) == {"version": None, "mode": "recommended", "has_record": False}
    assert change(auth, pref(auth), "综合").status_code == 409
    from tests.test_draft_api import url
    from tests.test_draft_collections import read, write

    path = url(identity)
    draft = client.put(
        path, headers=auth, json=write(read(auth, path), "未完成的初次草稿")
    )
    assert draft.status_code == 200, draft.text
    provider["mode"] = "auth"
    response, _ = start(auth, config, pref(auth))
    assert response.status_code == 202, response.text
    failed = test_training.wait_run(auth, response.json()["id"]).json()
    assert failed["status"] == "failed" and failed["random_mode"] == "first"
    assert not pref(auth)["has_record"]
    provider["mode"] = "ok"
    response, _ = start(auth, config, pref(auth))
    result = test_training.wait_run(auth, response.json()["id"]).json()
    assert result["random_mode"] == "first" and result["target"]["difficulty"] == "基础"
    with Session(engine) as session:
        runs = session.exec(
            select(TrainingRun).where(TrainingRun.user_id == owner)
        ).all()
        assert all(
            r.recommendation_delivered_at is None and r.formal_submitted_at is None
            for r in runs
        )
        assert session.get(RandomPreference, owner) is None


def test_preference_cas_owner_replay_fixed_freeze_and_empty_pool(ready, provider):
    owner, auth, identity, config, *_ = ready
    formal(ready)
    original = client.get(test_submissions.url(identity), headers=auth).json()
    baseline = pref(auth)
    barrier = Barrier(2)

    def save_mode(mode):
        barrier.wait(5)
        return change(auth, baseline, mode)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(save_mode, ["基础", "综合"]))
    assert sorted(r.status_code for r in results) == [200, 409]
    assert change(auth, baseline, "recommended").status_code == 409
    _, other = account()
    assert pref(other)["version"] is None
    assert client.get(PREFERENCE).status_code == 401
    assert (
        client.put(PREFERENCE, headers=auth, json={"mode": "基础"}).status_code == 422
    )
    fixed = change(auth, pref(auth), "综合").json()
    response, _ = start(auth, config, fixed)
    assert response.status_code == 409 and response.json()["detail"]["access"]
    assert all(
        item["target"]["difficulty"] == "综合"
        for item in response.json()["detail"]["access"]
    )
    fixed = change(auth, pref(auth), "基础").json()
    provider["mode"] = "hold"
    provider["received"].clear()
    response, body = start(auth, config, fixed)
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    assert provider["received"].wait(5)
    updated = change(auth, fixed, "recommended")
    assert updated.status_code == 200
    replay = client.post("/api/v1/training/random", headers=auth, json=body)
    assert replay.status_code == 202 and replay.json()["id"] == run_id
    assert (
        replay.json()["random_mode"] == "基础"
        and replay.json()["target"]["difficulty"] == "基础"
    )
    provider["release"].set()
    completed = test_training.wait_run(auth, run_id).json()
    assert completed["status"] == "completed", completed
    with Session(engine) as session:
        run = session.get(TrainingRun, uuid.UUID(run_id))
        assert run.recommendation_delivered_at is None
    assert client.get(test_submissions.url(identity), headers=auth).json() == original
    assert pref(auth)["mode"] == "recommended"


def test_recommended_publication_once_failure_stop_and_idempotent_delivery(
    ready, provider
):
    owner, auth, identity, config, *_ = ready
    formal(ready)
    provider["mode"] = "auth"
    response, _ = start(auth, config, pref(auth))
    failed_id = response.json()["id"]
    assert test_training.wait_run(auth, failed_id).json()["status"] == "failed"
    provider["mode"] = "hold"
    provider["received"].clear()
    response, _ = start(auth, config, pref(auth))
    stopped_id = response.json()["id"]
    assert provider["received"].wait(5)
    assert (
        client.post(
            f"/api/v1/training/tasks/{stopped_id}/stop", headers=auth
        ).status_code
        == 200
    )
    provider["release"].set()
    assert test_training.wait_run(auth, stopped_id).json()["status"] == "stopped"
    provider["mode"] = "ok"
    response, body = start(auth, config, pref(auth))
    run_id = response.json()["id"]
    assert test_training.wait_run(auth, run_id).json()["status"] == "completed"
    with Session(engine) as session:
        rows = session.exec(
            select(TrainingRun).where(TrainingRun.user_id == owner)
        ).all()
        facts = [
            (r.id, r.recommendation_delivered_at)
            for r in rows
            if r.recommendation_delivered_at
        ]
        assert len(facts) == 1 and str(facts[0][0]) == run_id
        run = session.get(TrainingRun, uuid.UUID(run_id))
        assert run.selection["delivered_before"] == 0 and run.launch_mode == "practice"
    assert (
        client.post("/api/v1/training/random", headers=auth, json=body).json()["id"]
        == run_id
    )
    response, _ = start(auth, config, pref(auth))
    next_id = response.json()["id"]
    assert test_training.wait_run(auth, next_id).json()["status"] == "completed"
    with Session(engine) as session:
        run = session.get(TrainingRun, uuid.UUID(next_id))
        assert run.selection["delivered_before"] == 1
        assert (
            session.get(TrainingRun, facts[0][0]).recommendation_delivered_at
            == facts[0][1]
        )


def test_late_retained_recommended_case_counts_once(ready, provider, tmp_path):
    import json
    import time
    from pathlib import Path

    _, auth, _, config, process, _ = ready
    formal(ready)
    test_training.stop_worker(process)
    response, body = start(auth, config, pref(auth))
    run_id = response.json()["id"]
    worker, control = test_training.start_worker(
        tmp_path, provider, run_id, before_accept=True, observe_accept=True
    )
    try:
        deadline = time.monotonic() + 8
        while (
            not Path(str(control) + ".accepting").exists()
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)
        assert Path(str(control) + ".accepting").exists()
        assert (
            client.post(
                f"/api/v1/training/tasks/{run_id}/stop", headers=auth
            ).status_code
            == 200
        )
        with Session(engine) as session:
            assert (
                session.get(TrainingRun, uuid.UUID(run_id)).recommendation_delivered_at
                is None
            )
        settings = json.loads(control.read_text())
        settings["before_accept"] = False
        control.write_text(json.dumps(settings))
        deadline = time.monotonic() + 5
        while (
            not Path(str(control) + ".accept_finished").exists()
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)
        assert Path(str(control) + ".accept_finished").exists()
        result = client.get(f"/api/v1/training/tasks/{run_id}", headers=auth).json()
        assert result["status"] == "stopped" and result["case"]
        with Session(engine) as session:
            timestamp = session.get(
                TrainingRun, uuid.UUID(run_id)
            ).recommendation_delivered_at
            assert timestamp
        assert (
            client.post("/api/v1/training/random", headers=auth, json=body).json()[
                "case"
            ]
            == result["case"]
        )
        with Session(engine) as session:
            assert (
                session.get(TrainingRun, uuid.UUID(run_id)).recommendation_delivered_at
                == timestamp
            )
    finally:
        settings = json.loads(control.read_text())
        settings["before_accept"] = False
        control.write_text(json.dumps(settings))
        test_training.stop_worker(worker)


def test_fifth_actual_recommendation_uses_real_verified_history_after_seven_days(
    tmp_path, provider, monkeypatch
):
    from datetime import UTC, datetime, timedelta

    from app.training import routes
    from tests.test_capability_evidence_api import (
        test_five_actual_new_cases_verify_fail_and_recover,
    )
    from tests.test_independent_api import frozen, origin

    case = frozen.__wrapped__()
    existing = origin.__wrapped__(provider, case)
    test_five_actual_new_cases_verify_fail_and_recover(
        tmp_path, provider, existing, case
    )
    auth, origin_id, config, _ = existing
    proof = client.get("/api/v1/capabilities/evidence", headers=auth).json()
    verified = proof["states"][0]
    assert verified["status"] == "verified"

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(UTC) + timedelta(days=8)

    monkeypatch.setattr(routes, "datetime", Later)
    provider["candidate"] = test_training.candidate
    worker, _ = test_training.start_worker(tmp_path, provider, str(origin_id))
    try:
        for index in range(5):
            response, _ = start(auth, config, pref(auth))
            assert response.status_code == 202, response.text
            result = test_training.wait_run(auth, response.json()["id"]).json()
            assert result["status"] == "completed", result
            if index == 4:
                assert result["recommendation_reason"] == "seventh_day_review"
                assert result["target"] == verified["target"]
                assert (
                    result["current_mode"] == "practice"
                    and result["independent_outcome"] is None
                )
        assert client.get("/api/v1/capabilities/evidence", headers=auth).json() == proof
    finally:
        test_training.stop_worker(worker)
