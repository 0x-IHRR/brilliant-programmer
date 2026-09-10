"""Only random synthetic accounts and records in the ticket's own database."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session

from app.core.db import engine
from app.deletion.models import ErasedObject, ErasedRow
from app.main import app
from app.training.models import TrainingRun
from tests import test_accounts
from tests.test_accounts import client
from tests.test_guided import frozen as frozen_case
from tests.test_model_config import account
from tests.test_project_training_rules import material as material

frozen = frozen_case

URL = "/api/v1/records"


@pytest.fixture(autouse=True)
def isolated_client(monkeypatch):
    # Independent scenarios must not consume the shared suite's login/IP bucket.
    # Requests within a scenario still share the real persistent rate limiter.
    with TestClient(app, client=(f"deletion-{uuid.uuid4()}", 50000)) as scenario:
        monkeypatch.setattr(test_accounts, "client", scenario)
        monkeypatch.setitem(globals(), "client", scenario)
        yield


def create_run(owner):
    with Session(engine) as session:
        row = TrainingRun(
            user_id=owner,
            config_version=uuid.uuid4(),
            destination="https://api.example.com/v1",
            model_id="fake",
            status="failed",
            selection={"entry": "random", "private": "synthetic-delete-me"},
            target={
                "capability_id": "network.trace",
                "difficulty": "basic",
                "background": "general",
            },
        )
        session.add(row)
        session.commit()
        return row.id


def request_preview(auth, run):
    return client.post(
        URL + "/deletions/preview",
        headers=auth,
        json={
            "kind": "training",
            "target_id": str(run),
            "password": "local-test-password-only",
        },
    )


def test_reauthentication_exact_scope_idempotence_and_resurrection_guard():
    owner, auth = account()
    run = create_run(owner)
    response = request_preview(auth, run)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["objects"]["training"] == [str(run)]
    assert "synthetic-delete-me" not in response.text
    path = URL + "/deletions/" + preview["id"] + "/confirm"
    assert (
        client.post(path, headers=auth, json={"confirmation": "yes"}).status_code == 422
    )
    assert (
        client.post(
            path, headers=auth, json={"confirmation": "永久删除所列资料及副本"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            path, headers=auth, json={"confirmation": "永久删除所列资料及副本"}
        ).status_code
        == 200
    )
    with Session(engine) as session:
        row = session.get(TrainingRun, run)
        assert row.selection == {} and row.status == "deleted" and row.stop_requested
        assert session.get(ErasedObject, (owner, "training", run))
        assert session.get(
            ErasedRow, ("training_run", str(run), uuid.UUID(preview["id"]))
        )
        row.selection = {"private": "synthetic-delete-me"}
        session.add(row)
        with pytest.raises(DBAPIError):
            session.commit()
        session.rollback()
        with pytest.raises(DBAPIError):
            session.execute(
                text(
                    "UPDATE training_run SET candidate = CAST(:payload AS json) WHERE id=:id"
                ),
                {"id": run, "payload": '{"restored":true}'},
            )
            session.commit()
        session.rollback()


def test_cross_owner_bad_password_and_changed_scope_do_not_delete():
    owner, auth = account()
    _, other = account()
    run = create_run(owner)
    assert request_preview(other, run).status_code == 404
    assert (
        client.post(
            URL + "/deletions/preview",
            headers=auth,
            json={"kind": "training", "target_id": str(run), "password": "wrong"},
        ).status_code
        == 403
    )
    preview = request_preview(auth, run).json()
    with Session(engine) as session:
        row = session.get(TrainingRun, run)
        row.sources = [{"text": "new synthetic private copy"}]
        session.add(row)
        session.commit()
    path = URL + "/deletions/" + preview["id"] + "/confirm"
    assert (
        client.post(
            path, headers=other, json={"confirmation": "永久删除所列资料及副本"}
        ).status_code
        == 404
    )
    response = client.post(
        path, headers=auth, json={"confirmation": "永久删除所列资料及副本"}
    )
    assert response.status_code == 409, response.text
    with Session(engine) as session:
        assert session.get(TrainingRun, run).sources == [
            {"text": "new synthetic private copy"}
        ]


def test_archive_keeps_input_and_grants_but_deleted_record_is_not_readable():
    owner, auth = account()
    run = create_run(owner)
    assert (
        client.post(
            URL + "/archive",
            headers=auth,
            json={"kind": "training", "target_id": str(run), "archived": True},
        ).status_code
        == 204
    )
    with Session(engine) as session:
        assert (
            session.get(TrainingRun, run).selection["private"] == "synthetic-delete-me"
        )
    assert all(
        r["id"] != str(run)
        for r in client.get("/api/v1/training/tasks", headers=auth).json()
    )
    p = request_preview(auth, run).json()
    assert (
        client.post(
            URL + "/deletions/" + p["id"] + "/confirm",
            headers=auth,
            json={"confirmation": "永久删除所列资料及副本"},
        ).status_code
        == 200
    )
    assert client.get(f"/api/v1/training/tasks/{run}", headers=auth).status_code == 410
    assert (
        client.get(
            f"/api/v1/training/tasks/{run}/submissions", headers=auth
        ).status_code
        == 410
    )
    assert client.get(URL, headers=auth).json()[0]["deleted"] is True


def test_history_copies_erased_without_deleting_later_case_or_answer(frozen):
    from app.training.history_protocol import freeze_history
    from app.training.independent_models import IndependentWork
    from app.training.independent_service import capture_history

    case, sources = frozen
    owner, auth = account()
    old, later = create_run(owner), create_run(owner)
    with Session(engine) as session:
        run = session.get(TrainingRun, old)
        run.candidate = case.model_dump(mode="json")
        run.sources = [s.model_dump() for s in sources]
        session.add(run)
        newer = session.get(TrainingRun, later)
        newer.candidate = case.model_dump(mode="json")
        session.add(newer)
        history = freeze_history({old: case}).model_dump(mode="json")
        session.add(
            IndependentWork(
                run_id=later,
                candidate=case.model_dump(mode="json"),
                history_snapshot=history,
                comparison_plan={"snapshot": history},
            )
        )
        session.commit()
    p = request_preview(auth, old).json()
    assert p["affects_seen_history"]
    assert p["comparison_only_runs"] == [str(later)]
    assert (
        client.post(
            URL + "/deletions/" + p["id"] + "/confirm",
            headers=auth,
            json={"confirmation": "永久删除所列资料及副本"},
        ).status_code
        == 200
    )
    with Session(engine) as session:
        work = session.get(IndependentWork, later)
        assert work.history_snapshot is None and work.comparison_plan is None
        assert work.candidate == case.model_dump(mode="json")
        assert session.get(TrainingRun, later).candidate == case.model_dump(mode="json")
        with pytest.raises(ValueError, match="deleted_seen_history_unavailable"):
            capture_history(session, session.get(TrainingRun, later))
    # Deleting the later record can add an empty-only marker without modifying
    # the previously appended comparison-erasure receipt.
    p = request_preview(auth, later).json()
    assert (
        client.post(
            URL + "/deletions/" + p["id"] + "/confirm",
            headers=auth,
            json={"confirmation": "永久删除所列资料及副本"},
        ).status_code
        == 200
    )


def test_quality_shared_bytes_keep_other_owner_and_old_report_cannot_replay(tmp_path):
    import hashlib
    import json

    from app.quality.import_report import load
    from app.quality.import_report import save as import_report
    from app.quality.models import QualityEvidence, QualityReport
    from tests.test_model_config import save
    from tests.test_quality_import import bundle

    owner, auth = account()
    other, other_auth = account()
    config = save(auth).json()
    path, digest, report, files = bundle(tmp_path, owner, config)
    report, digest, files = load(path, digest, tmp_path)
    foreign = report.model_copy(
        update={
            "artifact_id": uuid.uuid4(),
            "binding": report.binding.model_copy(update={"user_id": other}),
        }
    )
    with Session(engine) as session:
        import_report(session, report, digest, files)
        session.commit()
    with Session(engine) as session:
        import_report(
            session,
            foreign,
            hashlib.sha256(foreign.model_dump_json().encode()).hexdigest(),
            files,
        )
        session.commit()
    source_hash = report.cases[0].sources[0].text_sha256
    private_hash = report.samples[0].answer_sha256
    for who, headers in ((owner, auth), (other, other_auth)):
        run = create_run(who)
        with Session(engine) as session:
            row = session.get(TrainingRun, run)
            row.sources = [{"text": files[source_hash].decode()}]
            session.add(row)
            session.commit()
        p = request_preview(headers, run).json()
        assert p["objects"]["quality"] == [
            str(report.artifact_id if who == owner else foreign.artifact_id)
        ]
        result = client.post(
            URL + "/deletions/" + p["id"] + "/confirm",
            headers=headers,
            json={"confirmation": "永久删除所列资料及副本"},
        )
        assert result.status_code == 200, result.text
        with Session(engine) as session:
            erased = session.get(
                QualityReport,
                report.artifact_id if who == owner else foreign.artifact_id,
            )
            assert erased.report == {}
            if who == owner:
                assert (
                    session.get(QualityEvidence, source_hash).content
                    == files[source_hash]
                )
                assert session.get(
                    QualityReport, foreign.artifact_id
                ).report == json.loads(foreign.model_dump_json())
            else:
                assert session.get(QualityEvidence, private_hash) is None
    with Session(engine) as session:
        with pytest.raises(ValueError, match="deleted report identity"):
            import_report(session, report, digest, files)
    # A different account's explicit NEW report can legitimately retain the same
    # public bytes. A global hash tombstone must not forbid this operation.
    third, _ = account()
    fresh = report.model_copy(
        update={
            "artifact_id": uuid.uuid4(),
            "binding": report.binding.model_copy(update={"user_id": third}),
        }
    )
    with Session(engine) as session:
        import_report(
            session,
            fresh,
            hashlib.sha256(fresh.model_dump_json().encode()).hexdigest(),
            files,
        )
        session.commit()
        assert session.get(QualityEvidence, source_hash).content == files[source_hash]


def wait_for_advisory_waiter(name):
    import time

    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        with Session(engine) as session:
            waiting = session.execute(
                text(
                    "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE application_name=:name AND wait_event='advisory')"
                ),
                {"name": name},
            ).scalar_one()
        if waiting:
            return
        time.sleep(0.01)
    pytest.fail(
        "the competing transaction never reached its real PostgreSQL advisory lock"
    )


@pytest.mark.parametrize("first", ["import", "erase"])
def test_same_sha_import_and_erase_serialize_then_recheck_live_references(
    tmp_path, monkeypatch, first
):
    import hashlib
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from app.deletion import quality
    from app.deletion.service import erase
    from app.quality.import_report import load
    from app.quality.import_report import save as import_report
    from app.quality.models import QualityEvidence, QualityReport
    from tests.test_model_config import save
    from tests.test_quality_import import bundle

    owner, auth = account()
    other, _ = account()
    path, digest, report, files = bundle(tmp_path, owner, save(auth).json())
    report, digest, files = load(path, digest, tmp_path)
    foreign = report.model_copy(
        update={
            "artifact_id": uuid.uuid4(),
            "binding": report.binding.model_copy(update={"user_id": other}),
        }
    )
    with Session(engine) as session:
        import_report(session, report, digest, files)
        session.commit()
    run = create_run(owner)
    sha = report.cases[0].sources[0].text_sha256
    with Session(engine) as session:
        row = session.get(TrainingRun, run)
        row.sources = [{"text": files[sha].decode()}]
        session.add(row)
        session.commit()
    receipt = uuid.UUID(request_preview(auth, run).json()["id"])
    locked, release = threading.Event(), threading.Event()
    real_lock = quality.lock_hashes
    held = False

    def barrier(session, values):
        nonlocal held
        real_lock(session, values)
        if session.info.get("operation") == first and not held:
            held = True
            locked.set()
            assert release.wait(12)

    monkeypatch.setattr(quality, "lock_hashes", barrier)
    prefix = "bp31-sha-" + uuid.uuid4().hex

    def execute(operation):
        with Session(engine) as session:
            session.info["operation"] = operation
            session.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": prefix + operation},
            )
            if operation == "erase":
                return erase(session, owner, receipt).completed_at
            result = import_report(
                session,
                foreign,
                hashlib.sha256(foreign.model_dump_json().encode()).hexdigest(),
                files,
            )
            session.commit()
            return result.id

    second = "erase" if first == "import" else "import"
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(execute, first)
        try:
            assert locked.wait(8)
            b = pool.submit(execute, second)
            wait_for_advisory_waiter(prefix + second)
        finally:
            release.set()
        assert a.result(timeout=15)
        assert b.result(timeout=15)
    with Session(engine) as session:
        assert session.get(QualityReport, report.artifact_id).report == {}
        assert session.get(QualityReport, foreign.artifact_id).report
        for key, raw in files.items():
            assert session.get(QualityEvidence, key).content == raw


def test_read_projection_and_erase_use_ordered_snapshots():
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from app.deletion.service import erase
    from app.training.projection import read_snapshot

    owner, auth = account()
    run = create_run(owner)
    receipt = uuid.UUID(request_preview(auth, run).json()["id"])
    name = "bp31-read-" + uuid.uuid4().hex
    started = threading.Event()

    def delete():
        with Session(engine) as session:
            session.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": name},
            )
            started.set()
            return erase(session, owner, receipt).completed_at

    with ThreadPoolExecutor(max_workers=1) as pool:
        with read_snapshot(owner) as snapshot:
            before = snapshot.get(TrainingRun, run).selection
            future = pool.submit(delete)
            assert started.wait(5)
            wait_for_advisory_waiter(name)
            snapshot.expire_all()
            assert snapshot.get(TrainingRun, run).selection == before
        assert future.result(timeout=8)
    # A read opened after successful erasure cannot reuse the old request's
    # identity map or a repeatable-read snapshot established before lock release.
    assert client.get(f"/api/v1/training/tasks/{run}", headers=auth).status_code == 410
    with read_snapshot(owner) as snapshot:
        assert snapshot.get(TrainingRun, run).selection == {}


@pytest.mark.parametrize("kind", ["training", "topic"])
def test_reader_waits_for_delete_before_establishing_its_rr_snapshot(monkeypatch, kind):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from app.deletion import service

    owner, auth = account()
    if kind == "topic":
        from tests.test_topics import seed_route

        run = uuid.UUID(seed_route(owner)[0])
        endpoint = f"/api/v1/topics/{run}"
    else:
        run = create_run(owner)
        endpoint = f"/api/v1/training/tasks/{run}"
    preview = client.post(
        URL + "/deletions/preview",
        headers=auth,
        json={
            "kind": kind,
            "target_id": str(run),
            "password": "local-test-password-only",
        },
    )
    assert preview.status_code == 200, preview.text
    receipt = uuid.UUID(preview.json()["id"])
    entered, release = threading.Event(), threading.Event()
    original_collect = service.collect
    name = "bp31-delete-first-" + uuid.uuid4().hex

    def barrier(session, *args):
        result = original_collect(session, *args)
        if session.info.get("delete_barrier"):
            entered.set()
            assert release.wait(12)
        return result

    monkeypatch.setattr(service, "collect", barrier)

    def delete():
        with Session(engine) as session:
            session.info["delete_barrier"] = True
            return service.erase(session, owner, receipt).completed_at

    # Identify the actual public GET's advisory lock acquisition. This adds
    # only an observation tag and leaves the production lock/isolation unchanged.
    from sqlalchemy import event

    def tag(_connection, cursor, statement, _parameters, _context, _executemany):
        if "pg_advisory_lock_shared" in statement:
            cursor.execute("SELECT set_config('application_name', %s, false)", (name,))
        elif "pg_advisory_unlock_shared" in statement:
            cursor.execute("RESET application_name")

    event.listen(engine, "before_cursor_execute", tag)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            deleting = pool.submit(delete)
            try:
                assert entered.wait(5)
                reading = pool.submit(client.get, endpoint, headers=auth)
                wait_for_advisory_waiter(name)
            finally:
                release.set()
            assert deleting.result(timeout=8)
            response = reading.result(timeout=8)
            assert response.status_code == 410, response.text
            assert "synthetic-delete-me" not in response.text
    finally:
        release.set()
        event.remove(engine, "before_cursor_execute", tag)


@pytest.mark.parametrize("kind", ["topic", "jd", "project"])
def test_each_source_closure_preserves_an_unselected_version_and_rejects_late_copy(
    kind,
):
    from app.project.models import ProjectRun
    from app.project.training_models import (
        ProjectInput,
        ProjectMaterials,
        ProjectTopic,
        ProjectVersion,
    )
    from app.training.jd_models import JDAnalysis, JDDocument, JDRoute, JDTopic
    from app.training.topic_models import Topic, TopicCase, TopicJob, TopicVersion

    owner, auth = account()
    with Session(engine) as session:
        selected, other = Topic(user_id=owner), Topic(user_id=owner)
        session.add_all([selected, other])
        session.flush()
        topic_id = selected.id
        job = TopicJob(
            id=uuid.uuid4(),
            topic_id=topic_id,
            user_id=owner,
            input_text="private-source-synthetic",
            config_version=uuid.uuid4(),
            destination="https://example.com/v1",
            model_id="fake",
            status="completed",
        )
        job_id = job.id
        version_id = uuid.uuid4()
        session.add(job)
        session.flush()
        session.add(
            TopicVersion(
                id=version_id,
                topic_id=topic_id,
                snapshot={"private": "private-source-synthetic"},
            )
        )
        unrelated = TopicVersion(
            id=uuid.uuid4(),
            topic_id=other.id,
            snapshot={"private": "unselected-source-synthetic"},
        )
        session.add(unrelated)
        session.flush()
        unrelated_id = unrelated.id
        source_identity = topic_id
        if kind == "jd":
            session.add(JDTopic(topic_id=topic_id))
            session.add(
                JDDocument(
                    id=job_id, topic_id=topic_id, text="private-source-synthetic"
                )
            )
            session.flush()
            session.add(
                JDAnalysis(
                    document_id=job_id, snapshot={"private": "private-source-synthetic"}
                )
            )
            session.add(
                JDRoute(
                    version_id=version_id,
                    document_id=job_id,
                    snapshot={"private": "private-source-synthetic"},
                )
            )
        if kind == "project":
            project = ProjectRun(
                user_id=owner,
                url="https://github.com/example/synthetic",
                config_version=uuid.uuid4(),
                destination="https://example.com/v1",
                model_id="fake",
                snapshot={"fragments": [{"text": "private-source-synthetic"}]},
                project_map={"private": "private-source-synthetic"},
            )
            session.add(project)
            session.flush()
            source_identity = project.id
            session.add(ProjectTopic(topic_id=topic_id, project_run_id=project.id))
            session.add(
                ProjectInput(
                    id=job_id,
                    topic_id=topic_id,
                    project_run_id=project.id,
                    snapshot=project.snapshot,
                    project_map=project.project_map,
                )
            )
            session.flush()
            session.add(
                ProjectVersion(
                    version_id=version_id,
                    input_id=job_id,
                    snapshot={"private": "private-source-synthetic"},
                )
            )
        run = TrainingRun(
            user_id=owner,
            config_version=uuid.uuid4(),
            destination="https://example.com/v1",
            model_id="fake",
            selection={"topic_id": str(topic_id)},
            target={"capability_id": "network.trace"},
            sources=[{"text": "private-source-synthetic"}],
        )
        session.add(run)
        session.flush()
        run_id = run.id
        session.add(
            TopicCase(run_id=run.id, candidate={"private": "private-source-synthetic"})
        )
        if kind == "project":
            session.add(
                ProjectMaterials(
                    run_id=run.id, origins=[{"quote": "private-source-synthetic"}]
                )
            )
        session.commit()
    response = client.post(
        URL + "/deletions/preview",
        headers=auth,
        json={
            "kind": "project" if kind == "project" else "topic",
            "target_id": str(source_identity),
            "password": "local-test-password-only",
        },
    )
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["objects"]["training"] == [str(run_id)]
    response = client.post(
        URL + f"/deletions/{receipt['id']}/confirm",
        headers=auth,
        json={"confirmation": "永久删除所列资料及副本"},
    )
    assert response.status_code == 200, response.text
    with Session(engine) as session:
        assert session.get(TopicVersion, version_id).snapshot == {}
        assert session.get(TopicVersion, unrelated_id).snapshot == {
            "private": "unselected-source-synthetic"
        }
        assert session.get(TrainingRun, run_id).sources == []
        assert session.get(TopicJob, job_id).input_text == ""
        assert session.get(TopicCase, run_id).candidate == {}
        if kind == "jd":
            assert session.get(JDDocument, job_id).text == ""
            assert session.get(JDAnalysis, job_id).snapshot == {}
            assert session.get(JDRoute, version_id).snapshot == {}
        if kind == "project":
            assert session.get(ProjectRun, source_identity).snapshot is None
            assert session.get(ProjectInput, job_id).snapshot == {}
            assert session.get(ProjectVersion, version_id).snapshot == {}
            assert session.get(ProjectMaterials, run_id).origins == []
        session.add(
            TopicVersion(
                id=uuid.uuid4(),
                topic_id=topic_id,
                snapshot={"restored": "private-source-synthetic"},
            )
        )
        with pytest.raises(DBAPIError):
            session.commit()
        session.rollback()


def test_read_snapshot_uses_one_checkout_and_releases_after_body_errors(monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy import create_engine

    from app.training import projection

    # Same ticket database, deliberately bounded independent pool. Four readers
    # can coexist using exactly four checkouts, including an exception path.
    bounded = create_engine(engine.url, pool_size=4, max_overflow=0, pool_timeout=1)
    monkeypatch.setattr(projection, "engine", bounded)
    together = threading.Barrier(4)
    ids = [uuid.uuid4() for _ in range(4)]

    def read(index):
        try:
            with projection.read_snapshot(ids[index]) as session:
                assert (
                    session.execute(text("SHOW transaction_isolation")).scalar_one()
                    == "repeatable read"
                )
                assert (
                    session.execute(text("SHOW transaction_read_only")).scalar_one()
                    == "on"
                )
                together.wait(timeout=4)
                if index == 0:
                    session.execute(text("SELECT 1/0"))
        except DBAPIError:
            assert index == 0

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(read, i) for i in range(4)]
            for future in futures:
                future.result(timeout=8)
        with Session(engine) as session:
            for identity in ids:
                assert session.execute(
                    text("SELECT pg_try_advisory_xact_lock(:key)"),
                    {"key": projection.erasure_lock_key(identity)},
                ).scalar_one()
    finally:
        bounded.dispose()


def test_password_change_invalidates_preview_admin_has_no_other_owner_scope():
    from app.core.security import get_password_hash
    from app.deletion.models import DeletionRequest
    from app.models import User

    owner, auth = account()
    admin, admin_auth = account()
    run = create_run(owner)
    preview = request_preview(auth, run).json()
    with Session(engine) as session:
        user = session.get(User, owner)
        user.hashed_password = get_password_hash("synthetic-replacement-password")
        session.add(user)
        elevated = session.get(User, admin)
        elevated.is_superuser = True
        session.add(elevated)
        session.commit()
    path = URL + f"/deletions/{preview['id']}/confirm"
    assert (
        client.post(
            path, headers=auth, json={"confirmation": "永久删除所列资料及副本"}
        ).status_code
        == 409
    )
    assert request_preview(admin_auth, run).status_code == 404
    assert (
        client.post(
            path, headers=admin_auth, json={"confirmation": "永久删除所列资料及副本"}
        ).status_code
        == 404
    )
    with Session(engine) as session:
        assert (
            session.get(TrainingRun, run).selection["private"] == "synthetic-delete-me"
        )
        receipt = session.get(DeletionRequest, uuid.UUID(preview["id"]))
        receipt.target_id = uuid.uuid4()
        session.add(receipt)
        with pytest.raises(DBAPIError):
            session.commit()
        session.rollback()


def test_mid_erase_failure_rolls_back_markers_and_content_then_same_receipt_retries(
    monkeypatch,
):
    from app.deletion import quality
    from app.deletion.models import DeletionRequest

    owner, auth = account()
    run = create_run(owner)
    receipt = request_preview(auth, run).json()
    real = quality.erase_unreferenced

    def failure(_session, _blobs):
        raise RuntimeError("controlled failure after private row erasure")

    monkeypatch.setattr(quality, "erase_unreferenced", failure)
    endpoint = URL + f"/deletions/{receipt['id']}/confirm"
    with pytest.raises(RuntimeError, match="controlled failure"):
        client.post(
            endpoint, headers=auth, json={"confirmation": "永久删除所列资料及副本"}
        )
    with Session(engine) as session:
        assert session.get(TrainingRun, run).selection == {
            "entry": "random",
            "private": "synthetic-delete-me",
        }
        assert session.get(ErasedObject, (owner, "training", run)) is None
        assert (
            session.get(DeletionRequest, uuid.UUID(receipt["id"])).completed_at is None
        )
    monkeypatch.setattr(quality, "erase_unreferenced", real)
    response = client.post(
        endpoint, headers=auth, json={"confirmation": "永久删除所列资料及副本"}
    )
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("same", [False, True])
def test_deleted_quality_binding_cannot_mask_other_failure_or_revive_old_pass(
    tmp_path, same
):
    import hashlib
    import json

    from fastapi import HTTPException

    from app.deletion.models import ErasedObject
    from app.quality.import_report import load
    from app.quality.import_report import save as import_report
    from app.quality.models import QualityReport
    from app.quality.service import require_start, status
    from app.training.submission_models import Submission
    from tests.test_model_config import save
    from tests.test_quality_api import publish, report_for
    from tests.test_quality_import import bundle

    owner, auth = account()
    config = save(auth).json()
    old, _ = report_for(owner, config, failed=not same)
    publish(old)
    second_config = (
        config
        if same
        else {**config, "version": str(uuid.uuid4()), "model_id": "other-binding"}
    )
    path, digest, report, files = bundle(tmp_path, owner, second_config)
    report, _, files = load(path, digest, tmp_path)
    report = report.model_copy(update={"supersedes": old.artifact_id if same else None})
    with Session(engine) as session:
        import_report(
            session,
            report,
            hashlib.sha256(report.model_dump_json().encode()).hexdigest(),
            files,
        )
        session.commit()
    # Only this report references this exact accepted original identity. The
    # different binding's report is unrelated and must remain applicable.
    raw = json.loads(files[report.samples[0].answer_sha256])
    original = raw["original"]
    run = create_run(owner)
    with Session(engine) as session:
        session.add(
            Submission(
                id=uuid.UUID(original["id"]),
                run_id=run,
                sequence=1,
                config_version=uuid.UUID(second_config["version"]),
                destination=second_config["service_url"],
                model_id=second_config["model_id"],
                input_hash=uuid.uuid4().hex,
                answers=original["answers"],
                status="completed",
            )
        )
        session.commit()
    preview = request_preview(auth, run).json()
    assert preview["objects"]["quality"] == [str(report.artifact_id)]
    response = client.post(
        URL + f"/deletions/{preview['id']}/confirm",
        headers=auth,
        json={"confirmation": "永久删除所列资料及副本"},
    )
    assert response.status_code == 200, response.text
    with Session(engine) as session:
        state, chosen = status(session, old.binding, None)
        assert state == ("unverified" if same else "failed")
        assert chosen.id == (report.artifact_id if same else old.artifact_id)
        assert session.get(QualityReport, old.artifact_id).report == old.model_dump(
            mode="json"
        )
        marker = session.get(ErasedObject, (owner, "quality", report.artifact_id))
        assert len(marker.binding_digest) == 64
        if not same:
            with pytest.raises(HTTPException) as error:
                require_start(session, old.binding, None)
            assert error.value.status_code == 409
    if same:
        retest, _ = report_for(owner, config, supersedes=old.artifact_id)
        with pytest.raises(ValueError, match="predecessor"):
            publish(retest)
        retest = retest.model_copy(update={"supersedes": report.artifact_id})
        publish(retest)
        with Session(engine) as session:
            state, latest = status(session, old.binding, None)
            assert latest.id == retest.artifact_id
            assert state == "unverified"  # No sources supplied for applicability.


@pytest.mark.parametrize("active_deleted", [False, True])
def test_deleted_project_family_member_keeps_valid_sibling_readable(
    material, active_deleted
):
    from app.project.training_service import link_update
    from app.training.topic_models import Topic
    from tests.test_model_config import save
    from tests.test_project_updates import confirm, seeded

    owner, auth = account()
    config = save(auth).json()
    a, first = seeded(owner, config, material)
    assert confirm(auth, a, first.route.id).status_code == 200
    b, second = seeded(owner, config, material)
    with Session(engine) as session:
        link_update(
            session,
            session.get(Topic, b),
            first.route.id,
            second.repository,
            first.route.id,
        )
        session.commit()
    if not active_deleted:
        assert confirm(auth, b, second.route.id, first.route.id).status_code == 200
    before = client.get(f"/api/v1/project-training/{b}", headers=auth)
    assert before.status_code == 200, before.text
    preview = client.post(
        URL + "/deletions/preview",
        headers=auth,
        json={
            "kind": "topic",
            "target_id": str(a),
            "password": "local-test-password-only",
        },
    )
    assert preview.status_code == 200, preview.text
    erased = client.post(
        URL + f"/deletions/{preview.json()['id']}/confirm",
        headers=auth,
        json={"confirmation": "永久删除所列资料及副本"},
    )
    assert erased.status_code == 200, erased.text
    assert client.get(f"/api/v1/project-training/{a}", headers=auth).status_code == 410
    after = client.get(f"/api/v1/project-training/{b}", headers=auth)
    assert after.status_code == 200, after.text
    assert after.json()["current"] == before.json()["current"]
    assert after.json()["active"] == (
        None if active_deleted else before.json()["active"]
    )
    listed = client.get("/api/v1/project-training", headers=auth)
    assert listed.status_code == 200, listed.text
    assert str(b) in listed.text and str(a) not in [
        item["topic"]["id"] for item in listed.json()
    ]


@pytest.mark.parametrize("kind", ["topic", "jd"])
def test_valid_source_deletion_keeps_other_source_get_and_list(kind):
    from tests.test_jds import seeded
    from tests.test_model_config import save
    from tests.test_topics import seed_route

    owner, auth = account()
    config = save(auth).json()
    identities = []
    for _ in range(2):
        if kind == "topic":
            identity = seed_route(owner)[0]
        else:
            identity, document = seeded(auth, config)
            selected = client.post(
                f"/api/v1/jds/{identity}/select",
                headers=auth,
                json={"document_id": document, "role_index": 0},
            )
            assert selected.status_code == 200, selected.text
        identities.append(identity)
    a, b = identities
    path = "/api/v1/topics" if kind == "topic" else "/api/v1/jds"
    before = client.get(f"{path}/{b}", headers=auth)
    assert before.status_code == 200, before.text
    preview = client.post(
        URL + "/deletions/preview",
        headers=auth,
        json={"kind": "topic", "target_id": a, "password": "local-test-password-only"},
    )
    assert preview.status_code == 200, preview.text
    result = client.post(
        URL + f"/deletions/{preview.json()['id']}/confirm",
        headers=auth,
        json={"confirmation": "永久删除所列资料及副本"},
    )
    assert result.status_code == 200, result.text
    assert client.get(f"{path}/{a}", headers=auth).status_code == 410
    after = client.get(f"{path}/{b}", headers=auth)
    assert after.status_code == 200, after.text
    assert after.json() == before.json()
    listed = client.get(path, headers=auth)
    assert listed.status_code == 200, listed.text
    assert b in listed.text and a not in listed.text


@pytest.mark.parametrize("delete_first", [False, True])
def test_source_checkpoint_serializes_final_scope_and_cannot_restore(
    material, monkeypatch, delete_first
):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from app.deletion import service
    from app.project import worker
    from app.project.models import ProjectRun
    from tests.test_model_config import save
    from tests.test_project_updates import source

    owner, auth = account()
    config = save(auth).json()
    identity = source(owner, config, material)
    snapshot = material[0]
    changed = snapshot.model_copy(update={"requests": snapshot.requests + 1})
    preview = client.post(
        URL + "/deletions/preview",
        headers=auth,
        json={
            "kind": "project",
            "target_id": str(identity),
            "password": "local-test-password-only",
        },
    )
    assert preview.status_code == 200, preview.text
    receipt = uuid.UUID(preview.json()["id"])
    if not delete_first:
        worker.checkpoint(identity, changed)
        rejected = client.post(
            URL + f"/deletions/{receipt}/confirm",
            headers=auth,
            json={"confirmation": "永久删除所列资料及副本"},
        )
        assert rejected.status_code == 409, rejected.text
        with Session(engine) as session:
            assert session.get(ProjectRun, identity).snapshot == changed.model_dump(
                mode="json"
            )
        return
    held, release, waiting = threading.Event(), threading.Event(), threading.Event()
    original_collect, original_owner = service.collect, worker.lock_owner

    def collect(session, *args):
        result = original_collect(session, *args)
        held.set()
        assert release.wait(10)
        return result

    def owner_lock(session, user_id):
        waiting.set()
        return original_owner(session, user_id)

    monkeypatch.setattr(service, "collect", collect)
    monkeypatch.setattr(worker, "lock_owner", owner_lock)

    def deleting():
        with Session(engine) as session:
            return service.erase(session, owner, receipt).completed_at

    with ThreadPoolExecutor(max_workers=2) as pool:
        delete = pool.submit(deleting)
        try:
            assert held.wait(5)
            checkpoint = pool.submit(worker.checkpoint, identity, changed)
            assert waiting.wait(5)
            assert not checkpoint.done()
        finally:
            release.set()
        assert delete.result(timeout=8)
        checkpoint.result(timeout=8)
    with Session(engine) as session:
        run = session.get(ProjectRun, identity)
        assert run.status == "deleted" and run.snapshot is None
    worker.checkpoint(identity, changed)
    with Session(engine) as session:
        assert session.get(ProjectRun, identity).snapshot is None


def test_batch_reference_guard_rejects_mixed_delete_and_matches_old_predicate(tmp_path):
    import hashlib

    from app.deletion.models import DeletionRequest, ErasedAttachment
    from app.quality.import_report import load
    from app.quality.import_report import save as import_report
    from app.quality.models import QualityEvidence
    from tests.test_model_config import save
    from tests.test_quality_import import bundle

    owner, auth = account()
    path, digest, _, _ = bundle(tmp_path, owner, save(auth).json())
    report, digest, files = load(path, digest, tmp_path)
    live = report.samples[0].answer_sha256
    unused_bytes = uuid.uuid4().bytes
    unused = hashlib.sha256(unused_bytes).hexdigest()
    with Session(engine) as session:
        import_report(session, report, digest, files)
        session.add(QualityEvidence(sha256=unused, content=unused_bytes))
        session.commit()
    run = create_run(owner)
    receipt_id = uuid.UUID(request_preview(auth, run).json()["id"])
    with Session(engine) as session:
        assert session.get(DeletionRequest, receipt_id).user_id == owner
        for sha in (live, unused):
            session.add(ErasedAttachment(request_id=receipt_id, sha256=sha))
        session.commit()
        for sha in (live, unused, report.cases[0].sources[0].text_sha256, "0" * 64):
            old = session.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM quality_report WHERE jsonb_path_exists(report::jsonb, '$.** ? (@ == $sha)', jsonb_build_object('sha', CAST(:sha AS text))))"
                ),
                {"sha": sha},
            ).scalar_one()
            new = session.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM erasure_referenced_hashes(ARRAY[CAST(:sha AS text)]))"
                ),
                {"sha": sha},
            ).scalar_one()
            assert new == old
        with pytest.raises(
            DBAPIError, match="shared quality evidence remains referenced"
        ):
            with session.begin_nested():
                session.execute(
                    text("DELETE FROM quality_evidence WHERE sha256=ANY(:values)"),
                    {"values": [unused, live]},
                )
        assert session.get(QualityEvidence, unused).content == unused_bytes
        assert session.get(QualityEvidence, live).content == files[live]
        # Unauthorized rows still fail the original per-row immutable guard.
        with pytest.raises(DBAPIError):
            with session.begin_nested():
                session.execute(
                    text("DELETE FROM quality_evidence WHERE sha256=:sha"),
                    {"sha": report.cases[0].case_sha256},
                )
        # The unreferenced row is individually authorized and can be erased.
        session.execute(
            text("DELETE FROM quality_evidence WHERE sha256=:sha"), {"sha": unused}
        )
        session.commit()
        assert session.get(QualityEvidence, live).content == files[live]
