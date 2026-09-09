"""Real owner routes, PostgreSQL and a separate TLS model worker."""

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlmodel import Session, select

from app.core.db import engine
from app.training.models import TrainingRun
from app.training.preference_models import RandomPreference
from tests import test_practices, test_submissions, test_training
from tests.test_accounts import client
from tests.test_model_config import account

provider = test_training.provider
ready = test_submissions.ready
practice_ready = test_practices.ready
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
    control = ready[-1]
    options = json.loads(control.read_text())
    control.write_text(json.dumps({**options, "before_submission_ok": True}))
    formal(ready)
    deadline = time.monotonic() + 5
    while not control.with_name(control.name + ".submission_ok_pending").exists():
        assert time.monotonic() < deadline
        time.sleep(0.02)
    original = client.get(test_submissions.url(identity), headers=auth).json()
    assert original["submissions"][0]["attempts"][0]["code"] == "unknown"
    control.write_text(json.dumps(options))
    deadline = time.monotonic() + 5
    while original["submissions"][0]["attempts"][0]["code"] == "unknown":
        assert time.monotonic() < deadline, "final submission attempt was not persisted"
        original = client.get(test_submissions.url(identity), headers=auth).json()
        time.sleep(0.02)
    assert original["submissions"][0]["attempts"][0]["code"] == "ok"
    assert original["awarded_points"] == 10
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


@pytest.mark.parametrize("mode", ["ok", "forged"])
def test_late_retained_recommended_case_counts_once(ready, provider, tmp_path, mode):
    import json
    import time
    from pathlib import Path

    _, auth, _, config, process, _ = ready
    formal(ready)
    provider["mode"] = mode
    calls_before = len(provider["requests"])
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
        with ThreadPoolExecutor(1) as pool:
            stopping = pool.submit(
                client.post, f"/api/v1/training/tasks/{run_id}/stop", headers=auth
            )
            try:
                deadline = time.monotonic() + 5
                while True:
                    with Session(engine) as session:
                        run = session.get(TrainingRun, uuid.UUID(run_id))
                        assert run.recommendation_delivered_at is None
                        if run.stop_requested:
                            break
                    assert time.monotonic() < deadline
                    time.sleep(0.02)
                assert not stopping.done()
            finally:
                settings = json.loads(control.read_text())
                settings["before_accept"] = False
                control.write_text(json.dumps(settings))
            assert stopping.result(5).status_code == 200
        deadline = time.monotonic() + 5
        while (
            not Path(str(control) + ".accept_finished").exists()
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)
        assert Path(str(control) + ".accept_finished").exists()
        result = client.get(f"/api/v1/training/tasks/{run_id}", headers=auth).json()
        assert result["status"] == "stopped"
        assert bool(result["case"]) == (mode == "ok")
        assert result["attempts"][0]["total_tokens"] == 20
        assert len(provider["requests"]) == calls_before + 1
        if mode == "forged":
            assert result["code"] in {"cancelled", "stopped"}
        with Session(engine) as session:
            timestamp = session.get(
                TrainingRun, uuid.UUID(run_id)
            ).recommendation_delivered_at
            assert bool(timestamp) == (mode == "ok")
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


def test_committed_original_counts_before_related_settlement(ready):
    from app.capabilities.evidence_models import OriginalOrder

    _, auth, identity, config, worker, _ = ready
    test_training.stop_worker(worker)
    body = test_submissions.payload(config)
    response = client.post(test_submissions.url(identity), headers=auth, json=body)
    assert response.status_code == 202
    try:
        state = response.json()
        assert (
            state["submissions"][0]["status"] == "checking"
            and state["awarded_points"] == 0
        )
        with Session(engine) as session:
            assert session.get(OriginalOrder, uuid.UUID(body["request_id"]))
            assert (
                session.get(TrainingRun, uuid.UUID(identity)).formal_submitted_at
                is None
            )
        assert pref(auth)["has_record"]
        saved = change(auth, pref(auth), "recommended")
        assert saved.status_code == 200
        next_run, _ = start(auth, config, saved.json())
        assert (
            next_run.status_code == 202
            and next_run.json()["random_mode"] == "recommended"
        )
        client.post(
            f"/api/v1/training/tasks/{next_run.json()['id']}/stop", headers=auth
        )
        assert client.get(test_submissions.url(identity), headers=auth).json() == state
    finally:
        client.post(
            f"/api/v1/training/tasks/{identity}/submissions/{body['request_id']}/stop",
            headers=auth,
        )




@pytest.mark.parametrize("mode", ["unrelated", "auth"])
def test_unsettled_original_survives_unrelated_or_system_failure(ready, provider, mode):
    _, auth, identity, config, *_ = ready
    if mode == "unrelated":
        provider["relevance"] = "unrelated"
    else:
        provider["mode"] = mode
    response = client.post(
        test_submissions.url(identity),
        headers=auth,
        json=test_submissions.payload(config),
    )
    assert response.status_code == 202
    state = test_submissions.wait_submission(auth, identity)
    assert state["submissions"][0]["status"] in {"needs_supplement", "failed"}
    assert state["awarded_points"] == 0
    with Session(engine) as session:
        assert session.get(TrainingRun, uuid.UUID(identity)).formal_submitted_at is None
    assert pref(auth)["has_record"]
    assert change(auth, pref(auth), "基础").status_code == 200


def test_practice_only_answer_and_award_do_not_create_original_history(practice_ready):
    auth, identity, _, *_ = practice_ready
    help_id = test_practices.demo(practice_ready)
    test_practices.receipt(
        auth, identity, test_practices.publish(auth, identity, help_id)
    )
    path = test_practices.url(identity, help_id)
    response = client.post(
        path, headers=auth, json=test_practices.body(practice_ready[2])
    )
    assert response.status_code == 202
    result = test_practices.wait_practice(auth, path)
    assert result["completed"] and result["records"]["awarded_points"] == 10
    assert not pref(auth)["has_record"]
    assert change(auth, pref(auth), "进阶").status_code == 409


def test_cancelled_accept_finishes_before_next_recommendation_snapshot(
    ready, provider, tmp_path
):
    import json
    import time
    from pathlib import Path

    _, auth, _, config, worker, _ = ready
    formal(ready)
    for _ in range(3):
        response, _ = start(auth, config, pref(auth))
        assert test_training.wait_run(auth, response.json()["id"]).json()["case"]
    test_training.stop_worker(worker)
    # Capture preference before A obtains its model permission/User lock.
    preference = pref(auth)
    fourth, _ = start(auth, config, preference)
    fourth_id = fourth.json()["id"]
    process, control = test_training.start_worker(
        tmp_path, provider, fourth_id, before_accept=True
    )
    pool = ThreadPoolExecutor(2)
    try:
        deadline = time.monotonic() + 8
        while (
            not Path(str(control) + ".accepting").exists()
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)
        assert Path(str(control) + ".accepting").exists()
        stopping = pool.submit(
            client.post, f"/api/v1/training/tasks/{fourth_id}/stop", headers=auth
        )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with Session(engine) as session:
                if session.get(TrainingRun, uuid.UUID(fourth_id)).stop_requested:
                    break
            time.sleep(0.02)
        else:
            raise AssertionError("stop intent not committed")
        starting = pool.submit(start, auth, config, preference)
        # Old code releases User while the cancelled to_thread still blocks at
        # accept: B can freeze count=3. Fixed code retains User through acceptance.
        from sqlalchemy import text

        deadline = time.monotonic() + 5
        while True:
            with Session(engine) as session:
                waiters = session.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND query LIKE 'SELECT \"user\".%FOR UPDATE%'"
                    )
                ).scalar_one()
            if waiters >= 2:
                break
            assert time.monotonic() < deadline, (
                "stop and next selection must wait for acceptance permission"
            )
            time.sleep(0.02)
        assert not stopping.done() and not starting.done()
        settings = json.loads(control.read_text())
        settings["before_accept"] = False
        control.write_text(json.dumps(settings))
        assert stopping.result(timeout=5).status_code == 200
        fifth, _ = starting.result(timeout=5)
        assert fifth.status_code == 202, fifth.text
        assert test_training.wait_run(auth, fifth.json()["id"]).json()["case"]
        with Session(engine) as session:
            a = session.get(TrainingRun, uuid.UUID(fourth_id))
            b = session.get(TrainingRun, uuid.UUID(fifth.json()["id"]))
            assert (
                a.recommendation_delivered_at and a.candidate and a.status == "stopped"
            )
            assert b.selection["delivered_before"] == 4
            assert b.recommendation_delivered_at >= a.recommendation_delivered_at
    finally:
        settings = json.loads(control.read_text())
        settings["before_accept"] = False
        control.write_text(json.dumps(settings))
        pool.shutdown(wait=True)
        test_training.stop_worker(process)
