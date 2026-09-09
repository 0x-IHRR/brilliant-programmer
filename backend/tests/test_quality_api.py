"""Real owner APIs/transactions with explicitly synthetic imported report fixtures."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy.exc import ProgrammingError
from sqlmodel import Session, select

from app.core.db import engine
from app.model_config.service import lock_owner
from app.quality.import_report import save as import_report
from app.quality.models import QualityDisposition, QualityReport
from app.quality.rules import Binding, SourceIdentity
from app.quality.service import freeze
from app.training.evaluation_models import Evaluation
from app.training.evaluation_schema import EVALUATION_RULE
from app.training.models import TrainingRun
from tests.test_accounts import client
from tests.test_boss_api import seed_points
from tests.test_boss_api import start as boss_start
from tests.test_model_config import account, save
from tests.test_quality_rules import fixture


def report_for(owner, config, *, failed=False, sources=None, supersedes=None):
    report, source = fixture()
    report = report.model_copy(
        update={
            "binding": Binding(
                user_id=owner,
                config_version=uuid.UUID(config["version"]),
                destination=config["service_url"],
                model_id=config["model_id"],
                evaluation_rule=EVALUATION_RULE,
            ),
            "supersedes": supersedes,
        }
    )
    if sources:
        report = report.model_copy(
            update={
                "cases": [
                    c.model_copy(
                        update={"sources": [SourceIdentity.of(s) for s in sources]}
                    )
                    for c in report.cases
                ]
            }
        )
    if failed:
        rows = list(report.samples)
        rows[0] = rows[0].model_copy(update={"observed": "unclear"})
        rows[1] = rows[1].model_copy(update={"observed": "unclear"})
        report = report.model_copy(update={"samples": rows})
    return report, source


def publish(report):
    # Software-only fixtures enter the same serialized trusted-service seam;
    # they do not claim human annotation or use the production local importer.
    with Session(engine) as session:
        row = import_report(session, report, uuid.uuid4().hex * 2)
        session.commit()
        return row.id


def test_config_read_four_states_and_server_owned_gate():
    owner, auth = account()
    config = save(auth).json()
    assert config["quality"]["status"] == "unverified"
    seed_points(owner, config)
    report, _ = report_for(owner, config, failed=True)
    publish(report)
    failed = client.get("/api/v1/model-config", headers=auth).json()
    assert failed["quality"]["status"] == "failed"
    assert boss_start(auth, config).status_code == 409
    assert "samples" not in failed["quality"]
    assert "output_sha256" not in str(failed)
    _, other = account()
    assert client.get("/api/v1/model-config", headers=other).json() is None
    assert client.post(
        "/api/v1/model-config/quality", headers=auth, json={"status": "passed"}
    ).status_code in {404, 405}
    assert (
        save(
            auth, expected_version=config["version"], quality={"status": "passed"}
        ).status_code
        == 422
    )
    retest, _ = report_for(owner, config, supersedes=report.artifact_id)
    publish(retest)
    assert (
        client.get("/api/v1/model-config", headers=auth).json()["quality"]["status"]
        == "passed"
    )
    changed = save(auth, expected_version=config["version"]).json()
    assert changed["quality"]["status"] == "version_mismatch"
    assert changed["version"] != config["version"]


def seed(owner, config, source):
    with Session(engine) as session:
        run = TrainingRun(
            user_id=owner,
            config_version=uuid.UUID(config["version"]),
            destination=config["service_url"],
            model_id=config["model_id"],
            target={},
            selection={},
        )
        session.add(run)
        session.flush()
        evaluation = Evaluation(
            run_id=run.id,
            config_version=run.config_version,
            destination=run.destination,
            model_id=run.model_id,
            case_snapshot={},
            inputs={},
            sources=[source.model_dump()],
            status="completed",
        )
        session.add(evaluation)
        session.commit()
        return run.id


def decide(identity):
    with Session(engine) as session:
        run = session.get(TrainingRun, identity)
        lock_owner(session, run.user_id)
        result = freeze(session, run, session.get(Evaluation, identity))
        session.commit()
        return result.status


def test_first_disposition_preserves_history_and_denial_after_retest():
    owner, auth = account()
    config = save(auth).json()
    report, source = report_for(owner, config, failed=True)
    old = seed(owner, config, source)
    assert decide(old) == "unverified"
    publish(report)
    denied = seed(owner, config, source)
    assert decide(denied) == "failed"
    assert decide(old) == "unverified"
    retest, _ = report_for(owner, config, supersedes=report.artifact_id)
    publish(retest)
    assert decide(denied) == "failed"
    assert decide(seed(owner, config, source)) == "passed"
    with Session(engine) as session:
        assert (
            len(
                session.exec(
                    select(QualityDisposition).where(
                        QualityDisposition.run_id == denied
                    )
                ).all()
            )
            == 1
        )


def test_actual_score_config_is_not_current_saved_config():
    owner, auth = account()
    config = save(auth).json()
    report, source = report_for(owner, config, failed=True)
    publish(report)
    identity = seed(owner, config, source)
    changed = save(auth, expected_version=config["version"]).json()
    assert changed["quality"]["status"] == "version_mismatch"
    assert decide(identity) == "failed"
    assert decide(seed(owner, changed, source)) == "version_mismatch"


def test_import_cas_and_append_only():
    owner, auth = account()
    config = save(auth).json()
    report, _ = report_for(owner, config)
    publish(report)
    stale, _ = report_for(owner, config)
    with Session(engine) as session, pytest.raises(ValueError, match="predecessor"):
        import_report(session, stale, uuid.uuid4().hex * 2)
    with Session(engine) as session:
        row = session.get(QualityReport, report.artifact_id)
        row.outcome = "failed"
        session.add(row)
        with pytest.raises(ProgrammingError, match="immutable"):
            session.commit()


def test_import_and_settlement_share_owner_commit_order():
    owner, auth = account()
    config = save(auth).json()
    report, source = report_for(owner, config, failed=True)
    identity = seed(owner, config, source)
    entered = Event()
    with Session(engine) as session, ThreadPoolExecutor() as pool:
        import_report(session, report, uuid.uuid4().hex * 2)

        def settle():
            entered.set()
            return decide(identity)

        pending = pool.submit(settle)
        assert entered.wait(2)
        assert not pending.done()
        session.commit()
        assert pending.result(5) == "failed"
