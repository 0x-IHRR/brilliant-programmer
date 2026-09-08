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
