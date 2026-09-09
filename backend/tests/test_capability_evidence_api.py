"""Real owner API and persisted controlled TLS evidence; no model mocking."""

import uuid

from sqlalchemy.exc import DBAPIError
from sqlmodel import Session, select

from app.capabilities.evidence_models import OriginalOrder
from app.core.db import engine
from app.training.independent_models import IndependentObservation
from app.training.submission_models import Submission
from tests import test_independent_api
from tests.test_accounts import client
from tests.test_independent_api import evaluate
from tests.test_model_config import account

checked = test_independent_api.checked
provider = test_independent_api.provider
frozen = test_independent_api.frozen
origin = test_independent_api.origin


def test_actual_frozen_evidence_is_scoped_and_traceable(checked):
    auth, run_id, _ = checked
    result = evaluate(checked)
    assert result["independent_outcome"] == "independent_pass_candidate"
    response = client.get("/api/v1/capabilities/evidence", headers=auth)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    state = response.json()["states"][0]
    assert state["status"] == "unverified" and state["streak"] == 1
    entry = state["history"][0]["evidence"]
    assert entry["run_id"] == run_id
    assert entry["qualified_novelty"] and entry["judgment_ids"] == ["j1"]
    assert entry["order_source"] == "user_locked"
    assert (
        "help_boundary" not in response.text and "before_reasoning" not in response.text
    )
    assert (
        client.get("/api/v1/capabilities/evidence", headers=auth).json()
        == response.json()
    )
    _, other = account()
    assert (
        client.get("/api/v1/capabilities/evidence", headers=other).json()["states"]
        == []
    )
    assert client.get("/api/v1/capabilities/evidence").status_code == 401
    assert (
        client.post(
            "/api/v1/capabilities/evidence", headers=auth, json={"verified": True}
        ).status_code
        == 405
    )
    with Session(engine) as session:
        order = session.get(OriginalOrder, uuid.UUID(entry["original_id"]))
        assert order.position == 1
        order.position = 100
        session.add(order)
        try:
            session.commit()
            raise AssertionError("immutable ordering was rewritten")
        except DBAPIError:
            session.rollback()


def test_latest_observation_replaces_at_original_position_without_rewriting_history(
    checked,
):
    auth, run_id, _ = checked
    evaluate(checked)
    initial = client.get("/api/v1/capabilities/evidence", headers=auth).json()
    with Session(engine) as session:
        old = session.exec(
            select(IndependentObservation).where(
                IndependentObservation.run_id == uuid.UUID(run_id)
            )
        ).one()
        session.add(
            IndependentObservation(
                run_id=old.run_id,
                sequence=old.sequence + 100,
                frozen_sequence=old.frozen_sequence,
                original_id=old.original_id,
                target=old.target,
                case_digest=old.case_digest,
                outcome="disputed",
            )
        )
        session.commit()
    current = client.get("/api/v1/capabilities/evidence", headers=auth).json()[
        "states"
    ][0]
    assert current["streak"] == 0 and current["status"] == "unverified"
    assert len(current["history"]) == 1
    assert (
        current["history"][0]["evidence"]["order"]
        == initial["states"][0]["history"][0]["evidence"]["order"]
    )
    with Session(engine) as session:
        assert (
            len(
                session.exec(
                    select(IndependentObservation).where(
                        IndependentObservation.run_id == uuid.UUID(run_id)
                    )
                ).all()
            )
            == 2
        )
        assert (
            len(
                session.exec(
                    select(Submission).where(Submission.run_id == uuid.UUID(run_id))
                ).all()
            )
            == 1
        )


def test_five_actual_new_cases_verify_fail_and_recover(
    tmp_path, provider, origin, frozen
):
    import json

    from tests.capability_scenarios import comparisons, scenario
    from tests.test_evaluations import grading, start, wait
    from tests.test_submissions import wait_submission
    from tests.test_training import start_worker, stop_worker, wait_run

    auth, origin_id, config, _ = origin
    process, _ = start_worker(tmp_path, provider, str(origin_id))
    provider["grading"] = lambda context: grading_for(context)

    def grading_for(context):
        result = grading(
            context,
            "evidenced_fail"
            if context["inputs"]["original"][0]["value"] == 1
            else "pass",
        )
        value = context["task"]["evidence"][0]["facts"]["ack"]
        for item in result["items"]:
            item["grounding"][0].update(fact="ack", value=value)
            item["reason_claims"][0]["interpreted_fact_value"] = value
        return result

    results = []
    try:
        for index in range(5):
            case = scenario(frozen[0], index)
            provider["candidate"] = lambda payload, case=case: (
                comparisons(json.loads(payload["messages"][1]["content"]))
                if "new" in json.loads(payload["messages"][1]["content"])
                else case.model_dump()
            )
            response = client.post(
                f"/api/v1/training/tasks/{origin_id}/independent",
                headers=auth,
                json={
                    "request_id": str(uuid.uuid4()),
                    "expected_config_version": config["version"],
                    "disclosure_accepted": True,
                },
            )
            assert response.status_code == 202, response.text
            run_id = response.json()["id"]
            assert wait_run(auth, run_id).json()["status"] == "completed"
            submission = client.post(
                f"/api/v1/training/tasks/{run_id}/submissions",
                headers=auth,
                json={
                    "request_id": str(uuid.uuid4()),
                    "expected_config_version": config["version"],
                    "disclosure_accepted": True,
                    "answers": [
                        {
                            "judgment_id": "j1",
                            "value": 1 if index == 2 else 0,
                            "reason": "依据当前材料判断下一步。",
                        }
                    ],
                },
            )
            assert submission.status_code == 202, submission.text
            assert wait_submission(auth, run_id)["awarded_points"] == 10
            start(auth, run_id, config)
            assert wait(auth, run_id)["status"] == "completed"
            states = client.get("/api/v1/capabilities/evidence", headers=auth).json()[
                "states"
            ]
            results.append(states[0])
        assert [s["status"] for s in results] == [
            "unverified",
            "verified",
            "needs_consolidation",
            "needs_consolidation",
            "verified",
        ]
        assert [s["streak"] for s in results] == [1, 2, 0, 1, 2]
        assert results[2]["latest_verified_at"] == results[1]["latest_verified_at"]
        assert results[-1]["latest_verified_at"] != results[1]["latest_verified_at"]
        assert len(results[-1]["history"]) == 5
    finally:
        stop_worker(process)


def test_concurrent_original_submissions_have_unique_stable_owner_order(origin):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from app.training.models import TrainingRun

    auth, identity, config, _ = origin
    with Session(engine) as session:
        first = session.get(TrainingRun, identity)
        second = TrainingRun(
            user_id=first.user_id,
            config_version=first.config_version,
            destination=first.destination,
            model_id=first.model_id,
            target=first.target,
            selection=first.selection,
            sources=first.sources,
            candidate=first.candidate,
            status="completed",
            code="ready",
        )
        session.add(second)
        session.commit()
        second_id = second.id
    barrier = threading.Barrier(2)
    bodies = {}

    def submit(run_id):
        body = {
            "request_id": str(uuid.uuid4()),
            "expected_config_version": config["version"],
            "disclosure_accepted": True,
            "answers": [
                {"judgment_id": "j1", "value": 0, "reason": "需要先核对处理记录。"}
            ],
        }
        bodies[str(run_id)] = body
        barrier.wait(5)
        response = client.post(
            f"/api/v1/training/tasks/{run_id}/submissions", headers=auth, json=body
        )
        assert response.status_code == 202, response.text
        return response.json()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, [identity, second_id]))
        before = client.get("/api/v1/capabilities/evidence", headers=auth).json()
        history = before["states"][0]["history"]
        assert [row["evidence"]["order"] for row in history] == [1, 2]
        assert all(row["evidence"]["outcome"] == "practice" for row in history)
        assert len({row["evidence"]["original_id"] for row in history}) == 2
        for run_id, body in bodies.items():
            assert (
                client.post(
                    f"/api/v1/training/tasks/{run_id}/submissions",
                    headers=auth,
                    json=body,
                ).status_code
                == 202
            )
        assert (
            client.get("/api/v1/capabilities/evidence", headers=auth).json() == before
        )
        assert len(results) == 2
    finally:
        for run_id, body in bodies.items():
            assert (
                client.post(
                    f"/api/v1/training/tasks/{run_id}/submissions/{body['request_id']}/stop",
                    headers=auth,
                ).status_code
                == 200
            )
