import asyncio

from sqlmodel import Session

from app.core.db import engine
from app.model_config.service import lock_owner
from app.training.gate import call_credential
from tests.test_model_config import account, save


def test_cancellation_releases_credential_lock_before_stop_succeeds():
    user, headers = account()
    version = save(headers).json()["version"]
    import uuid

    async def run():
        reached = asyncio.Event()
        finished = asyncio.Event()

        async def dispatch():
            async with call_credential(user, uuid.UUID(version)):
                reached.set()
                await asyncio.Event().wait()
            finished.set()

        def stop():
            with Session(engine) as session:
                lock_owner(session, user)
            return True

        invocation = asyncio.create_task(dispatch())
        await asyncio.wait_for(reached.wait(), 3)
        stop_task = asyncio.create_task(asyncio.to_thread(stop))
        await asyncio.sleep(0.05)
        assert not stop_task.done()
        invocation.cancel()
        try:
            await invocation
        except asyncio.CancelledError:
            pass
        assert await asyncio.wait_for(stop_task, 3)

    asyncio.run(run())


def test_source_temporary_dns_failure_does_not_retry_model_budget(monkeypatch):
    import uuid

    from app.capabilities.catalog import CATALOG
    from app.model_config.connection import ProbeError
    from app.training import worker
    from app.training.models import TrainingRun

    run = TrainingRun(
        user_id=uuid.uuid4(),
        config_version=uuid.uuid4(),
        destination="https://example.com",
        model_id="fake-only",
        selection={"catalog_version": CATALOG.version},
        target={
            "capability_id": "network.delivery",
            "difficulty": "基础",
            "background_id": "network-evidence-v1",
        },
    )
    source_calls = []
    finished = []

    async def source_failure(capability_id):
        source_calls.append(capability_id)
        raise ProbeError("dns", "temporary source DNS failure", retry=True)

    monkeypatch.setattr(worker, "read_run", lambda _identity: run)
    monkeypatch.setattr(worker, "last_attempt", lambda _identity: None)
    monkeypatch.setattr(worker, "acquire_source", source_failure)
    monkeypatch.setattr(worker, "finish", lambda *result: finished.append(result))

    async def check():
        await asyncio.wait_for(worker.process(run.id), timeout=0.5)

    asyncio.run(check())
    assert source_calls == ["network.delivery"]
    assert finished == [(run.id, "dns", "temporary source DNS failure")]
    assert (run.attempts, run.generation_attempts) == (0, 0)
