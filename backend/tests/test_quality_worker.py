"""Real independent worker/TLS result held after IO, before owner settlement."""

import json
import uuid

from sqlmodel import Session

from app.core.db import engine
from app.model_config.service import lock_owner
from app.quality.models import QualityDisposition
from app.training.evaluation_models import Evaluation
from app.training.independent_service import record_frozen
from app.training.models import TrainingRun
from app.training.schema import Source
from tests import test_independent_api as independent
from tests.test_accounts import client
from tests.test_evaluations import start as evaluation_start
from tests.test_evaluations import wait as evaluation_wait
from tests.test_quality_api import publish, report_for
from tests.test_submissions import wait_submission
from tests.test_training import start_worker, stop_worker, wait_run

provider = independent.provider
frozen = independent.frozen
origin = independent.origin


def history(auth, identity):
    data = client.get("/api/v1/capabilities/evidence", headers=auth)
    assert data.status_code == 200, data.text
    return next(
        row["evidence"]
        for state in data.json()["states"]
        for row in state["history"]
        if row["evidence"]["run_id"] == identity
    )


def test_failure_import_between_actual_grading_and_commit_freezes_denial(
    tmp_path, provider, origin
):
    auth, _, config, _ = origin
    provider["grading"] = independent.controlled_grading
    identity, _ = independent.start_check(origin)
    process, control = start_worker(
        tmp_path, provider, identity, before_quality_settle=True
    )
    try:
        assert wait_run(auth, identity).json()["status"] == "completed"
        response = client.post(
            f"/api/v1/training/tasks/{identity}/submissions",
            headers=auth,
            json={
                "request_id": str(uuid.uuid4()),
                "expected_config_version": config["version"],
                "disclosure_accepted": True,
                "answers": [
                    {
                        "judgment_id": "j1",
                        "value": 0,
                        "reason": "提交成功已确认，应保留已有结果，避免重新执行。",
                    }
                ],
            },
        )
        assert response.status_code == 202, response.text
        assert wait_submission(auth, identity)["awarded_points"] == 10
        evaluation_start(auth, identity, config)
        independent.wait_until(type(control)(str(control) + ".quality_settling").exists)
        with Session(engine) as session:
            run = session.get(TrainingRun, uuid.UUID(identity))
            evaluation = session.get(Evaluation, run.id)
            owner = run.user_id
            sources = [Source.model_validate(s) for s in evaluation.sources]
        failed, _ = report_for(owner, config, failed=True, sources=sources)
        publish(failed)
        options = json.loads(control.read_text())
        options["before_quality_settle"] = False
        control.write_text(json.dumps(options))
        assert evaluation_wait(auth, identity)["status"] == "completed"
        row = history(auth, identity)
        assert row["outcome"] == "quality_failed" and not row["qualified_novelty"]
        assert row["grading_quality"] == "failed"
        retest, _ = report_for(
            owner, config, sources=sources, supersedes=failed.artifact_id
        )
        publish(retest)
        with Session(engine) as session:
            lock_owner(session, owner)
            run = session.get(TrainingRun, uuid.UUID(identity))
            record_frozen(session, run, session.get(Evaluation, run.id))
            session.commit()
            assert (
                session.get(QualityDisposition, (run.id, "original")).status == "failed"
            )
        assert history(auth, identity) == row
        assert wait_submission(auth, identity)["awarded_points"] == 10
    finally:
        options = json.loads(control.read_text())
        options["before_quality_settle"] = False
        control.write_text(json.dumps(options))
        stop_worker(process)
