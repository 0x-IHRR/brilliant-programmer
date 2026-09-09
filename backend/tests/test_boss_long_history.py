"""600 public fixtures -> actual original APIs/TLS worker/awards -> full Boss.

The cases are controlled fixtures, not 600 model-generated teaching examples.
No PracticeAward, OriginalOrder, Submission or points are seeded.
"""

import asyncio
import json
import time
import uuid

from sqlmodel import Session, select

from app.capabilities.evidence_models import OriginalOrder
from app.core.db import engine
from app.models import User
from app.training.boss_stages import PROMOTION_STAGES
from app.training.history_protocol import ComparisonPlan, wire_request
from app.training.independent_models import IndependentWork
from app.training.models import TrainingAttempt, TrainingRun
from app.training.queue import queue
from app.training.schema import scenario_fingerprint
from app.training.submission_models import PracticeAward, Submission, SubmissionAttempt
from tests import test_training
from tests.stage_scenarios import REFERENCE, candidate, public_history_cases
from tests.test_accounts import client
from tests.test_boss_api import start
from tests.test_model_config import account, save
from tests.test_submissions import wait_submission

provider = test_training.provider


def test_600_actual_original_rewards_then_all_8400_pairs_in_three_calls(
    tmp_path, provider
):
    owner, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    cases = list(public_history_cases(600))
    identities = [uuid.uuid4() for _ in cases]
    with Session(engine) as session:
        user = session.get(User, owner)
        # Isolate the 6000-point admission/history path from prerequisite Boss
        # promotions, which the separate stage settlement tests exercise.
        user.level = "传奇程序员"
        session.add(user)
        for identity, (case, sources) in zip(identities, cases, strict=True):
            session.add(
                TrainingRun(
                    id=identity,
                    user_id=owner,
                    config_version=uuid.UUID(config["version"]),
                    destination=config["service_url"],
                    model_id=config["model_id"],
                    target=case.target.model_dump(),
                    selection={
                        "catalog_version": "fullstack-v1.0.0",
                        "entry": "controlled_fixture",
                    },
                    status="completed",
                    code="ready",
                    candidate=case.model_dump(mode="json"),
                    sources=[s.model_dump(mode="json") for s in sources],
                    scenario_hash=scenario_fingerprint(case),
                )
            )
        session.commit()
    provider.update(candidate=candidate, source_text=REFERENCE)
    process, control = test_training.start_worker(
        tmp_path, provider, str(identities[0]), after_comparison_batch=1
    )
    try:
        assert client.get("/api/v1/boss/access", headers=auth).json()["points"] == 0
        for index, (identity, (case, _)) in enumerate(
            zip(identities, cases, strict=True)
        ):
            response = client.post(
                f"/api/v1/training/tasks/{identity}/submissions",
                headers=auth,
                json={
                    "request_id": str(uuid.uuid4()),
                    "expected_config_version": config["version"],
                    "disclosure_accepted": True,
                    "answers": [
                        {
                            "judgment_id": j.id,
                            "value": 0,
                            "reason": "依据当前材料的状态归属、约束与可观察结果，仍需核实未确认的证据。",
                        }
                        for j in case.judgments
                    ],
                },
            )
            assert response.status_code == 202, response.text
            state = wait_submission(auth, identity)
            assert (
                state["awarded_points"] == 10
                and state["total_points"] == (index + 1) * 10
            )
        # Last award can precede its attempt-finalization transaction. Observe
        # actual durable attempt outcomes, not an arbitrary delay.
        deadline = time.monotonic() + 10
        while True:
            with Session(engine) as session:
                attempts = session.exec(
                    select(SubmissionAttempt)
                    .join(Submission)
                    .join(TrainingRun)
                    .where(TrainingRun.user_id == owner)
                ).all()
                if len(attempts) == 600 and all(a.code == "ok" for a in attempts):
                    assert all(
                        a.prompt_tokens == 11
                        and a.completion_tokens == 9
                        and a.total_tokens == 20
                        for a in attempts
                    )
                    assert (
                        len(
                            session.exec(
                                select(PracticeAward).where(
                                    PracticeAward.user_id == owner
                                )
                            ).all()
                        )
                        == 600
                    )
                    orders = session.exec(
                        select(OriginalOrder).where(OriginalOrder.user_id == owner)
                    ).all()
                    assert {o.position for o in orders} == set(range(1, 601))
                    break
            assert time.monotonic() < deadline
            time.sleep(0.04)
        access = client.get("/api/v1/boss/access", headers=auth).json()
        assert access["points"] == 6000 and access["can_start"]
        launched = start(
            auth, config, expected_stage=PROMOTION_STAGES[-1].model_dump(mode="json")
        )
        assert launched.status_code == 202, launched.text
        identity = launched.json()["id"]
        marker = type(control)(str(control) + ".comparison_committed")
        deadline = time.monotonic() + 90
        while not marker.exists():
            assert time.monotonic() < deadline, (
                "first durable comparison batch not reached"
            )
            time.sleep(0.04)
        with Session(engine) as session:
            partial = session.get(IndependentWork, uuid.UUID(identity))
            checkpoint = partial.comparison_results
            assert len(checkpoint) == 1
            run = session.get(TrainingRun, uuid.UUID(identity))
            assert run.candidate is None and run.status == "running"
            assert (run.attempts, run.generation_attempts) == (2, 1)
        assert len(provider["requests"]) == 602
        process.kill()
        process.wait()

        async def stalled():
            async with queue.open_async():
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    jobs = await queue.job_manager.get_stalled_jobs(
                        task_name="training.generate", seconds_since_heartbeat=0.5
                    )
                    if any(j.task_kwargs.get("run_id") == identity for j in jobs):
                        return
                    await asyncio.sleep(0.02)
                raise AssertionError("killed worker not durably stalled")

        asyncio.run(stalled())
        process, _ = test_training.start_worker(tmp_path, provider, identity)
        deadline = time.monotonic() + 90
        while True:
            ready = client.get(
                f"/api/v1/training/tasks/{identity}", headers=auth
            ).json()
            if ready["status"] in {"completed", "failed", "stopped"}:
                break
            assert time.monotonic() < deadline, ready
            time.sleep(0.1)
        assert ready["status"] == "completed", ready
        with Session(engine) as session:
            work = session.get(IndependentWork, uuid.UUID(identity))
            plan = ComparisonPlan.model_validate_json(json.dumps(work.comparison_plan))
            assert len(plan.snapshot.runs) == 600
            assert {r.run_id for r in plan.snapshot.runs} == set(identities)
            assert len(plan.batches) == len(work.comparison_results) == 3
            assert sum(len(b.pairs) for b in plan.batches) == 8400
            assert all(
                len(wire_request(b, plan.model_id)) <= 1024 * 1024 for b in plan.batches
            )
            attempts = session.exec(
                select(TrainingAttempt).where(
                    TrainingAttempt.run_id == uuid.UUID(identity)
                )
            ).all()
            assert len(attempts) == 4 and all(a.code == "ok" for a in attempts)
            assert [r["batch"] for r in work.comparison_results] == [0, 1, 2]
            assert work.comparison_results[:1] == checkpoint
            assert len({r["attempt_id"] for r in work.comparison_results}) == 3
            assert work.novelty["assessment"]["status"] == "novelty_candidate"
        assert len(provider["requests"]) == 604
        assert client.get("/api/v1/boss/access", headers=auth).json()["points"] == 6000
    finally:
        test_training.stop_worker(process)
