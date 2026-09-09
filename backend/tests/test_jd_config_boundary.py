"""Checked Topic/JD commits serialize with persisted config revocation."""

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel import Session

from app.core.db import engine
from app.model_config.revocation import request_revocation
from app.training import topic_worker
from app.training.jd_models import JDDocument, JDTopic
from app.training.topic_models import TopicJob
from tests.test_accounts import client
from tests.test_jd_rules import sample
from tests.test_model_config import account, save
from tests.test_topics import begin, interpretation


def pending(kind):
    owner, auth = account()
    config = save(auth).json()
    body, state = begin(auth, config)
    identity = uuid.UUID(body["request_id"])
    with Session(engine) as session:
        job = session.get(TopicJob, identity)
        job.stage = "inspect"
        job.candidate = interpretation()
        if kind == "jd":
            doc, analysis = sample()
            job.input_text = doc.text
            job.candidate = analysis.model_dump(mode="json")
            session.add(JDTopic(topic_id=job.topic_id))
            session.add(JDDocument(id=identity, topic_id=job.topic_id, text=doc.text))
        session.add(job)
        session.commit()
        job_id = job.queue_job_id
    return owner, auth, config, identity, job_id, state["id"]


@pytest.mark.parametrize("kind", ["topic", "jd"])
def test_revocation_first_blocks_result(kind):
    owner, auth, config, identity, job, topic = pending(kind)
    request_revocation(owner, uuid.UUID(config["version"]))
    with pytest.raises(HTTPException):
        topic_worker.accept(
            identity,
            json.dumps({"accepted": True, "explanation": "controlled checked content"}),
            job,
        )
    with Session(engine) as session:
        assert session.get(TopicJob, identity).result_id is None
    client.post(f"/api/v1/topics/{topic}/jobs/{identity}/stop", headers=auth)


@pytest.mark.parametrize("kind", ["topic", "jd"])
def test_result_first_retained_and_revocation_waits(kind, monkeypatch):
    owner, auth, config, identity, job, topic = pending(kind)
    entered, release = Event(), Event()
    original = topic_worker.compare

    def after_permission(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(topic_worker, "compare", after_permission)
    with ThreadPoolExecutor(2) as pool:
        acceptance = pool.submit(
            topic_worker.accept,
            identity,
            json.dumps({"accepted": True, "explanation": "controlled checked content"}),
            job,
        )
        assert entered.wait(3)
        revocation = pool.submit(
            request_revocation, owner, uuid.UUID(config["version"])
        )
        try:
            deadline = time.monotonic() + 3
            blocked = False
            while time.monotonic() < deadline and not revocation.done():
                with engine.connect() as connection:
                    blocked = bool(
                        connection.execute(
                            text(
                                "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND cardinality(pg_blocking_pids(pid)) > 0 AND query LIKE '%model_config%')"
                            )
                        ).scalar()
                    )
                if blocked:
                    break
            assert blocked, "revocation must wait for checked-result config row lock"
        finally:
            release.set()
        assert acceptance.result(timeout=3)
        revocation.result(timeout=3)
    with Session(engine) as session:
        result = session.get(TopicJob, identity)
        assert result.status == "completed" and result.code == "ok" and result.result_id
    response = client.get(
        f"/api/v1/{'jds' if kind == 'jd' else 'topics'}/{topic}", headers=auth
    )
    assert response.status_code == 200
