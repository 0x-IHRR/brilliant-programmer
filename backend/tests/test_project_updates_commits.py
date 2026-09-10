"""Two controlled GitHub commits; real queue/TLS keeps the scored original intact."""

import hashlib
import uuid

import pytest
from sqlmodel import Session, select

from app.core.db import engine
from app.project.models import ProjectRun
from app.project.schema import Location, ProjectMap, Snapshot
from app.project.training_rules import ModuleGoal
from app.training.evaluation_models import Evaluation
from app.training.models import TrainingRun
from app.training.submission_models import PracticeAward, Submission
from tests import test_project as upstream
from tests.test_accounts import client
from tests.test_evaluations import (
    grading,
)
from tests.test_evaluations import (
    start as start_evaluation,
)
from tests.test_evaluations import (
    wait as wait_evaluation,
)
from tests.test_model_config import save
from tests.test_project_training_api import response_for
from tests.test_project_training_rules import material as material
from tests.test_project_updates import confirm, public
from tests.test_submissions import wait_submission
from tests.test_topics import wait_topic
from tests.test_training import provider as provider
from tests.test_training import start_worker, stop_worker, wait_run


@pytest.fixture
def github(tmp_path):
    directory = tmp_path / "github"
    directory.mkdir()
    yield from upstream.provider.__wrapped__(directory)


def frozen_material(identity, goal):
    with Session(engine) as session:
        source = session.get(ProjectRun, uuid.UUID(identity))
        snapshot = Snapshot.model_validate(source.snapshot)
        mapped = ProjectMap.model_validate(source.project_map)
    fragment = snapshot.fragments[0]
    module = ModuleGoal(
        module_path=fragment.path,
        goal=goal,
        evidence=(
            Location(
                path=fragment.path,
                start=fragment.start,
                end=fragment.end,
                quote=fragment.text.rstrip("\n"),
            ),
        ),
    )
    return snapshot, mapped, module


def preserved(identity):
    with Session(engine) as session:
        return {
            "run": session.get(TrainingRun, identity).model_dump(mode="json"),
            "evaluation": session.get(Evaluation, identity).model_dump(mode="json"),
            "answers": [
                row.model_dump(mode="json")
                for row in session.exec(
                    select(Submission).where(Submission.run_id == identity)
                ).all()
            ],
            "award": session.get(PracticeAward, identity).model_dump(mode="json"),
        }


def test_new_commit_route_confirmation_keeps_entire_scored_original(
    github, provider, tmp_path, material, monkeypatch
):
    auth, source_a = upstream.start_project(github)
    directory = tmp_path / "read-a"
    directory.mkdir()
    worker, _ = upstream.start_worker(directory, github, source_a)
    try:
        acquired_a = upstream.wait_run(auth, source_a)
        assert acquired_a["status"] == "completed", acquired_a
    finally:
        stop_worker(worker)
    config = save(auth, service_url=provider["url"]).json()
    contents_a = frozen_material(source_a, material[2].goal)
    provider["candidate"] = response_for(contents_a)
    provider["grading"] = grading
    body_a = {
        "request_id": str(uuid.uuid4()),
        "topic_id": str(uuid.uuid4()),
        "project_run_id": source_a,
        "expected_config_version": config["version"],
        "disclosure_accepted": True,
    }
    assert (
        client.post(
            "/api/v1/project-training/analyze", headers=auth, json=body_a
        ).status_code
        == 202
    )
    directory = tmp_path / "teach-a"
    directory.mkdir()
    worker, _ = start_worker(directory, provider, body_a["request_id"])
    try:
        route_a = wait_topic(auth, body_a["topic_id"])["current"]
        assert confirm(auth, body_a["topic_id"], route_a["id"]).status_code == 200
        started = client.post(
            f"/api/v1/topics/{body_a['topic_id']}/start",
            headers=auth,
            json={
                "request_id": str(uuid.uuid4()),
                "expected_version": route_a["id"],
                "node_id": route_a["nodes"][0]["id"],
                "expected_config_version": config["version"],
                "disclosure_accepted": True,
            },
        )
        assert started.status_code == 202, started.text
        run_id = started.json()["id"]
        assert wait_run(auth, run_id).json()["status"] == "completed"
        submitted = client.post(
            f"/api/v1/training/tasks/{run_id}/submissions",
            headers=auth,
            json={
                "request_id": str(uuid.uuid4()),
                "answers": [
                    {
                        "judgment_id": "j1",
                        "value": 0,
                        "reason": "确认可能丢失，需要核对执行证据，不能凭未确认断定未执行。",
                    }
                ],
                "expected_config_version": config["version"],
                "disclosure_accepted": True,
            },
        )
        assert submitted.status_code == 202, submitted.text
        assert wait_submission(auth, run_id)["awarded_points"] == 10
        start_evaluation(auth, run_id, config)
        assert wait_evaluation(auth, run_id)["status"] == "completed"
    finally:
        stop_worker(worker)
    before = preserved(uuid.UUID(run_id))
    assert before["evaluation"]["inputs"] and before["evaluation"]["result"]
    assert all(
        source["version"] == upstream.SHA for source in before["evaluation"]["sources"]
    )
    frozen_a = public(auth, body_a["topic_id"])["current"]

    # Change only this controlled server's returned commit/tree/blob/text. No real repo write.
    new_text = upstream.SOURCE + b"# new fixed revision for update verification\n"
    monkeypatch.setattr(upstream, "SOURCE", new_text)
    monkeypatch.setattr(
        upstream,
        "BLOB",
        hashlib.sha1(
            b"blob " + str(len(new_text)).encode() + b"\0" + new_text
        ).hexdigest(),
    )
    monkeypatch.setattr(upstream, "TREE", "d" * 40)
    github["sha"] = "c" * 40
    save(auth, service_url=github["url"])
    _, source_b = upstream.start_project(github, auth)
    directory = tmp_path / "read-b"
    directory.mkdir()
    worker, _ = upstream.start_worker(directory, github, source_b)
    try:
        acquired_b = upstream.wait_run(auth, source_b)
        assert acquired_b["status"] == "completed", acquired_b
        assert acquired_b["reused_from_id"] is None
    finally:
        stop_worker(worker)
    contents_b = frozen_material(source_b, material[2].goal)
    assert contents_b[0].repository.commit != contents_a[0].repository.commit
    assert contents_b[0].fragments[0].text != contents_a[0].fragments[0].text
    config = save(auth, service_url=provider["url"]).json()
    provider["candidate"] = response_for(contents_b)
    body_b = {
        "request_id": str(uuid.uuid4()),
        "topic_id": str(uuid.uuid4()),
        "project_run_id": source_b,
        "previous_version_id": route_a["id"],
        "expected_active_version": route_a["id"],
        "expected_config_version": config["version"],
        "disclosure_accepted": True,
    }
    assert (
        client.post(
            "/api/v1/project-training/analyze", headers=auth, json=body_b
        ).status_code
        == 202
    )
    directory = tmp_path / "teach-b"
    directory.mkdir()
    worker, _ = start_worker(directory, provider, body_b["request_id"])
    try:
        assert wait_topic(auth, body_b["topic_id"])["jobs"][0]["status"] == "completed"
        updated = public(auth, body_b["topic_id"])
        route_b = updated["current"]["route"]
        assert updated["active"]["route"]["id"] == route_a["id"]
        assert route_b["nodes"][0]["id"] != route_a["nodes"][0]["id"]
        assert route_b["nodes"][0]["id"] not in updated["topic"]["completed_node_ids"]
        reference = updated["current"]["bindings"][0]["references"][0]["source"]
        assert reference["version"] == "c" * 40
        assert "new fixed revision" in reference["text"]
        assert (
            confirm(auth, body_b["topic_id"], route_b["id"], route_a["id"]).status_code
            == 200
        )
        assert (
            public(auth, body_a["topic_id"])["active"]["route"]["id"] == route_b["id"]
        )
        assert public(auth, body_a["topic_id"])["current"] == frozen_a
        assert preserved(uuid.UUID(run_id)) == before
    finally:
        stop_worker(worker)
