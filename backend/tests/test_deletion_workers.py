"""Real task worker/TLS plus deletion: synthetic data, task-only database."""

import json
import uuid
from datetime import UTC, datetime

from sqlmodel import Session, select

from app.core.db import engine
from app.models import User
from app.training.concept_models import ConceptHelp, HelpDelivery
from app.training.draft_collection import DraftCollection
from app.training.draft_models import TrainingDraft
from app.training.evaluation_models import Evaluation
from app.training.models import TrainingRun
from app.training.practice_models import PracticeDraft
from app.training.submission_models import PracticeAward, Submission
from tests import test_independent_api
from tests.test_accounts import client
from tests.test_deletions import URL, request_preview
from tests.test_evaluations import ready as evaluation_ready
from tests.test_evaluations import start, wait
from tests.test_training import provider as training_provider

ready = evaluation_ready
provider = training_provider


def test_actual_completed_feedback_erases_all_editor_and_answer_copies_keeps_grants(
    ready, provider
):
    auth, run_id, config, answer, _, _ = ready
    start(auth, run_id, config)
    assert wait(auth, run_id)["status"] == "completed"
    identity = uuid.UUID(run_id)
    with Session(engine) as session:
        run = session.get(TrainingRun, identity)
        owner = run.user_id
        user_before = session.get(User, owner).model_dump()
        award_before = session.get(PracticeAward, identity).model_dump()
        original = session.exec(
            select(Submission).where(Submission.run_id == identity)
        ).one()
        original_id = original.id
        # Persist the same privately entered content in all actual editor tables,
        # including a delivered demonstration's separately scoped draft.
        help_item = ConceptHelp(
            run_id=identity,
            created_sequence=run.event_sequence + 1,
            request={"topic": answer["reason"]},
            content={"private": answer["reason"]},
            inspection={"private": answer["reason"]},
            config_version=uuid.UUID(config["version"]),
            destination=config["service_url"],
            model_id=config["model_id"],
            status="ready",
        )
        session.add(help_item)
        session.flush()
        help_id = help_item.id
        session.add(
            HelpDelivery(
                run_id=identity,
                help_id=help_id,
                sequence=run.event_sequence + 2,
                exposure_sequence=run.event_sequence + 2,
                status="delivered",
                delivered_text=answer["reason"],
                direction="directional",
                content_hash="synthetic",
            )
        )
        for row in (
            TrainingDraft(
                run_id=identity,
                version=uuid.uuid4(),
                request_id=uuid.uuid4(),
                saved_at=datetime.now(UTC),
                progress={"answers": [answer]},
            ),
            PracticeDraft(
                help_id=help_id,
                run_id=identity,
                version=uuid.uuid4(),
                request_id=uuid.uuid4(),
                saved_at=datetime.now(UTC),
                progress={"answers": [answer]},
            ),
            DraftCollection(
                scope_key=f"{identity}:{help_id}",
                help_id=help_id,
                run_id=identity,
                data={"versions": [{"answers": [answer]}]},
            ),
        ):
            session.add(row)
        session.commit()
    request_count = len(provider["requests"])
    preview = request_preview(auth, identity)
    assert preview.status_code == 200, preview.text
    receipt = preview.json()
    assert receipt["affects_seen_history"]
    for table in (
        "training_submission",
        "training_evaluation",
        "practice_draft",
        "training_draft",
        "draft_collection",
        "concept_help",
        "help_delivery",
    ):
        assert receipt["private_rows"][table] >= 1
    response = client.post(
        URL + f"/deletions/{receipt['id']}/confirm",
        headers=auth,
        json={"confirmation": "永久删除所列资料及副本"},
    )
    assert response.status_code == 200, response.text
    for suffix in ("", "/submissions", "/evaluation", "/review", "/help", "/draft"):
        response = client.get(
            f"/api/v1/training/tasks/{identity}" + suffix, headers=auth
        )
        assert response.status_code == 410, (suffix, response.text)
    # Old device replay uses the exact original request identity and body.
    response = client.post(
        f"/api/v1/training/tasks/{identity}/submissions",
        headers=auth,
        json={
            "request_id": str(original_id),
            "answers": [answer],
            "expected_config_version": config["version"],
            "disclosure_accepted": True,
        },
    )
    assert response.status_code == 410, response.text
    with Session(engine) as session:
        assert session.get(User, owner).model_dump() == user_before
        assert session.get(PracticeAward, identity).model_dump() == award_before
        assert session.get(Submission, original_id).answers == []
        evaluation = session.get(Evaluation, identity)
        assert evaluation.inputs == evaluation.case_snapshot == {}
        assert evaluation.sources == [] and evaluation.result is None
        assert session.get(TrainingDraft, identity).progress == {}
        assert session.get(PracticeDraft, help_id).progress == {}
        assert session.get(DraftCollection, f"{identity}:{help_id}").data == {}
        assert session.get(ConceptHelp, help_id).request == {}
        assert (
            session.exec(select(HelpDelivery).where(HelpDelivery.help_id == help_id))
            .one()
            .delivered_text
            == ""
        )
    assert len(provider["requests"]) == request_count
    assert answer["reason"] not in json.dumps(
        client.get(URL, headers=auth).json(), ensure_ascii=False
    )


def test_delete_before_model_permission_prevents_late_worker_and_restart(
    tmp_path, provider
):
    import asyncio
    import time
    from pathlib import Path

    from app.training import worker
    from app.training.models import TrainingAttempt
    from tests.test_training import start_run, start_worker, stop_worker

    _, auth, run_id = start_run(provider)
    process, control = start_worker(
        tmp_path,
        provider,
        run_id,
        before_training_credential=True,
        observe_process_finish=True,
    )

    def marker(suffix):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if Path(str(control) + suffix).exists():
                return
            assert process.poll() is None
            time.sleep(0.02)
        raise AssertionError("real worker did not reach " + suffix)

    try:
        marker(".training_credential_waiting")
        preview = request_preview(auth, run_id)
        assert preview.status_code == 200, preview.text
        receipt = preview.json()
        response = client.post(
            URL + f"/deletions/{receipt['id']}/confirm",
            headers=auth,
            json={"confirmation": "永久删除所列资料及副本"},
        )
        assert response.status_code == 200, response.text
        assert provider["requests"] == []
        settings = json.loads(control.read_text())
        settings["before_training_credential"] = False
        control.write_text(json.dumps(settings))
        marker(".process_finished")
        with Session(engine) as session:
            run = session.get(TrainingRun, uuid.UUID(run_id))
            assert run.status == "deleted" and run.attempts == 0
            assert run.sources == [] and run.candidate is None
            assert (
                session.exec(
                    select(TrainingAttempt).where(TrainingAttempt.run_id == run.id)
                ).all()
                == []
            )
        # Actual production replay entry immediately exits on the durable tombstone.
        asyncio.run(worker.process(uuid.UUID(run_id)))
        assert provider["requests"] == []
    finally:
        stop_worker(process)



checked = test_independent_api.checked
origin = test_independent_api.origin
frozen = test_independent_api.frozen


def test_erased_evidence_is_unavailable_not_failure_and_practice_remains(
    checked, origin, provider
):
    from tests.test_training import wait_run

    auth, run_id, config = checked
    assert (
        test_independent_api.evaluate(checked)["independent_outcome"]
        == "independent_pass_candidate"
    )
    before = client.get("/api/v1/capabilities/evidence", headers=auth).json()["states"][
        0
    ]
    assert before["streak"] == 1
    grants = client.get("/api/v1/users/me", headers=auth).json()
    identity = uuid.UUID(run_id)
    with Session(engine) as session:
        award = session.get(PracticeAward, identity).model_dump()
    preview = request_preview(auth, run_id).json()
    result = client.post(
        URL + f"/deletions/{preview['id']}/confirm",
        headers=auth,
        json={"confirmation": "永久删除所列资料及副本"},
    )
    assert result.status_code == 200, result.text
    current = client.get("/api/v1/capabilities/evidence", headers=auth)
    assert current.status_code == 200, current.text
    state = current.json()["states"][0]
    evidence = state["history"][0]["evidence"]
    assert state["streak"] == 0
    assert evidence["outcome"] == "evidence_unavailable"
    assert not evidence["qualified_novelty"] and evidence["judgment_ids"] == []
    assert evidence["order"] == before["history"][0]["evidence"]["order"]
    assert client.get("/api/v1/users/me", headers=auth).json() == grants
    with Session(engine) as session:
        assert session.get(PracticeAward, identity).model_dump() == award
    count = len(provider["requests"])
    another, _ = test_independent_api.start_check(origin)
    result = wait_run(auth, another).json()
    assert (
        result["status"] == "failed"
        and result["code"] == "deleted_seen_history_unavailable"
    )
    assert result["attempts"] == [] and result["case"] is None
    assert len(provider["requests"]) == count
    provider.pop("candidate")
    ordinary = client.post(
        "/api/v1/training/random",
        headers=auth,
        json={
            "disclosure_accepted": True,
            "expected_config_version": config["version"],
        },
    )
    assert ordinary.status_code == 202, ordinary.text
    assert wait_run(auth, ordinary.json()["id"]).json()["status"] == "completed"
    assert len(provider["requests"]) == count + 1
