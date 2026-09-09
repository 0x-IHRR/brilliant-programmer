import json
import uuid

from sqlmodel import Session

from app.capabilities.catalog import CATALOG
from app.core.db import engine
from app.training.models import TrainingRun
from tests import test_guided, test_training
from tests.capability_scenarios import comparisons, scenario
from tests.test_accounts import client
from tests.test_evaluations import grading, start, wait
from tests.test_model_config import account, save
from tests.test_submissions import wait_submission
from tests.test_unlock_api import ADVANCED, BASE, open_request

provider = test_training.provider
frozen = test_guided.frozen


def test_direct_missing_proof_five_real_cases_open_retain_and_recover(
    tmp_path, provider, frozen, monkeypatch
):
    from app.capabilities import routes, unlocks

    _, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    assert open_request(auth).status_code == 409
    process = None
    ids = []

    def grading_for(context):
        value = context["task"]["evidence"][0]["facts"]["ack"]
        result = grading(
            context,
            "evidenced_fail"
            if context["inputs"]["original"][0]["value"] == 1
            else "pass",
        )
        for item in result["items"]:
            item["grounding"][0].update(fact="ack", value=value)
            item["reason_claims"][0]["interpreted_fact_value"] = value
        return result

    provider["grading"] = grading_for
    try:
        for index in range(5):
            sample = scenario(frozen[0], index)

            def response(payload, sample=sample):
                context = json.loads(payload["messages"][1]["content"])
                if "new" in context:
                    return comparisons(context)
                data = sample.model_dump()
                data["evidence"][0]["citations"] = [
                    {
                        "source_id": context["sources"][0]["id"],
                        "quote": context["sources"][0]["text"][:100],
                    }
                ]
                return data

            provider["candidate"] = response
            body = {
                "request_id": str(uuid.uuid4()),
                "target": BASE.model_dump(),
                "return_target": ADVANCED.model_dump(),
                "catalog_version": CATALOG.version,
                "mode": "independent",
                "disclosure_accepted": True,
                "expected_config_version": config["version"],
            }
            created = client.post("/api/v1/capabilities/start", headers=auth, json=body)
            assert created.status_code == 202, created.text
            identity = created.json()["id"]
            ids.append(identity)
            assert (
                created.json()["origin_id"] is None and created.json()["case"] is None
            )
            if process is None:
                process, _ = test_training.start_worker(tmp_path, provider, identity)
            ready = test_training.wait_run(auth, identity).json()
            assert ready["status"] == "completed", ready
            assert len(ready["attempts"]) == 2
            with Session(engine) as session:
                run = session.get(TrainingRun, uuid.UUID(identity))
                assert run.sources and run.origin_id is None
            submitted = client.post(
                f"/api/v1/training/tasks/{identity}/submissions",
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
            assert submitted.status_code == 202, submitted.text
            assert wait_submission(auth, identity)["awarded_points"] == 10
            start(auth, identity, config)
            assert wait(auth, identity)["status"] == "completed"
            proof = client.get("/api/v1/capabilities/evidence", headers=auth).json()[
                "states"
            ][0]
            assert (
                proof["status"]
                == [
                    "unverified",
                    "verified",
                    "needs_consolidation",
                    "needs_consolidation",
                    "verified",
                ][index]
            )
            opened = open_request(auth)
            assert opened.status_code == (409 if index == 0 else 200), opened.text
            if index in [2, 3, 4]:
                newer = CATALOG.model_copy(
                    update={"version": "controlled-next-catalog"}
                )
                with monkeypatch.context() as context:
                    context.setattr(routes, "CATALOG", newer)
                    context.setattr(unlocks, "CATALOG", newer)
                    result = client.post(
                        "/api/v1/capabilities/open",
                        headers=auth,
                        json={
                            "target": ADVANCED.model_dump(),
                            "catalog_version": newer.version,
                        },
                    )
                    assert result.status_code == (200 if index == 4 else 409), (
                        result.text
                    )
            assert (
                client.get("/api/v1/capabilities/evidence", headers=auth).json()[
                    "states"
                ][0]
                == proof
            )
        assert len(provider["requests"]) == 20
        assert len(ids) == len(set(ids)) == 5
    finally:
        if process:
            test_training.stop_worker(process)
        for identity in ids:
            client.post(f"/api/v1/training/tasks/{identity}/stop", headers=auth)


def test_source_failure_is_not_missing_ability_and_consumes_no_model_call(
    tmp_path, provider
):
    owner, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    provider["source_failure"] = True
    created = client.post(
        "/api/v1/capabilities/start",
        headers=auth,
        json={
            "request_id": str(uuid.uuid4()),
            "target": BASE.model_dump(),
            "catalog_version": CATALOG.version,
            "mode": "independent",
            "expected_config_version": config["version"],
            "disclosure_accepted": True,
        },
    )
    assert created.status_code == 202
    identity = created.json()["id"]
    process, _ = test_training.start_worker(tmp_path, provider, identity)
    try:
        result = test_training.wait_run(auth, identity).json()
        assert (
            result["status"] == "failed" and result["code"] == "source_unavailable"
        ), result
        assert (
            result["case"] is None
            and result["attempts"] == []
            and provider["requests"] == []
        )
        assert "公开依据" in result["message"]
        assert (
            client.get("/api/v1/capabilities/evidence", headers=auth).json()["states"]
            == []
        )
        assert open_request(auth).status_code == 409
    finally:
        test_training.stop_worker(process)


def test_retryable_source_dns_failure_exits_before_any_model_attempt(
    provider, monkeypatch
):
    import asyncio
    import socket

    import procrastinate

    from app.training import independent_worker
    from app.training.queue import DSN

    _, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    created = client.post(
        "/api/v1/capabilities/start",
        headers=auth,
        json={
            "request_id": str(uuid.uuid4()),
            "target": BASE.model_dump(),
            "catalog_version": CATALOG.version,
            "mode": "independent",
            "expected_config_version": config["version"],
            "disclosure_accepted": True,
        },
    )
    assert created.status_code == 202
    identity = uuid.UUID(created.json()["id"])
    with Session(engine) as session:
        job_id = session.get(TrainingRun, identity).queue_job_id
    lookups = []
    # Real process/acquire_source/PublicBackend; only the actual DNS resolver is
    # controlled. A second lookup fails immediately instead of hanging forever.
    async def execute():
        async def unavailable(host, port, **_kwargs):
            lookups.append((host, port))
            assert len(lookups) == 1, "source failure entered unbudgeted retry"
            raise socket.gaierror(socket.EAI_AGAIN, "controlled temporary DNS failure")

        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", unavailable)
        monkeypatch.setattr(independent_worker, "BACKOFF_SECONDS", [0])
        await independent_worker.process(identity)

    try:
        asyncio.run(execute())
        result = client.get(f"/api/v1/training/tasks/{identity}", headers=auth).json()
        assert result["status"] == "failed" and result["code"] == "dns"
        assert result["message"] == "服务地址无法解析"
        assert result["case"] is None and result["attempts"] == []
        assert len(lookups) == 1 and provider["requests"] == []
        with Session(engine) as session:
            run = session.get(TrainingRun, identity)
            assert run.attempts == run.generation_attempts == 0
            assert not run.sources
        assert client.get("/api/v1/capabilities/evidence", headers=auth).json()["states"] == []
        assert open_request(auth).status_code == 409
    finally:
        # This test invokes the real process directly, so retire its unclaimed
        # native queue job without leaving work for another test worker.
        with procrastinate.App(
            connector=procrastinate.SyncPsycopgConnector(conninfo=DSN)
        ).open() as app:
            app.job_manager.cancel_job_by_id(job_id, abort=True)
        client.post(f"/api/v1/training/tasks/{identity}/stop", headers=auth)
