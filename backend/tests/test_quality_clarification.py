"""Ending ordinary clarification freezes actual quality without requiring a key."""

import uuid

import pytest
from sqlmodel import Session

from app.core.db import engine
from app.quality.models import QualityDisposition
from app.training.models import TrainingRun
from app.training.schema import Source
from tests import test_evaluations as evaluations
from tests.test_accounts import client
from tests.test_quality_api import publish, report_for

provider = evaluations.provider
ready = evaluations.ready


@pytest.mark.parametrize("delete_config", [False, True])
def test_end_ordinary_clarification_retains_failed_quality_after_retest(
    ready, provider, delete_config
):
    auth, identity, config, *_ = ready
    provider["grading"] = lambda context: evaluations.grading(context, "unclear")
    evaluations.start(auth, identity, config)
    assert evaluations.wait(auth, identity)["status"] == "needs_clarification"
    with Session(engine) as session:
        run = session.get(TrainingRun, uuid.UUID(identity))
        owner = run.user_id
        sources = [Source.model_validate(s) for s in run.sources]
    failed, _ = report_for(owner, config, failed=True, sources=sources)
    publish(failed)
    if delete_config:
        deleted = client.delete(
            "/api/v1/model-config", headers=auth,
            params={"expected_version": config["version"]},
        )
        assert deleted.status_code == 204
    ended = client.post(
        evaluations.endpoint(identity) + "/clarification",
        headers=auth,
        json={"answers": None},
    )
    assert ended.status_code == 202
    assert ended.json()["status"] == "completed"
    assert ended.json()["grading_quality"] == "failed"
    with Session(engine) as session:
        frozen = session.get(QualityDisposition, (uuid.UUID(identity), "original"))
        assert frozen.status == "failed"
        assert frozen.binding["config_version"] == config["version"]
        old = frozen.model_dump()
    retest, _ = report_for(owner, config, sources=sources, supersedes=failed.artifact_id)
    publish(retest)
    replay = client.post(
        evaluations.endpoint(identity) + "/clarification",
        headers=auth,
        json={"answers": None},
    )
    assert replay.json() == ended.json()
    with Session(engine) as session:
        assert session.get(
            QualityDisposition, (uuid.UUID(identity), "original")
        ).model_dump() == old
