"""Deterministic cancellation boundaries of the real credential context manager."""

import asyncio
import uuid
from threading import Event

import pytest

from app.model_config.connection import CancelledCall, ProbeError
from app.training import gate


@pytest.mark.parametrize("body_error", ["cancelled", "provider", "none"])
def test_cleanup_second_cancellation_keeps_body_failure_and_releases_session(
    monkeypatch, body_error
):
    closing, release, closed = Event(), Event(), Event()

    class Session:
        def __init__(self, *_):
            pass

        def close(self):
            closing.set()
            assert release.wait(5)
            closed.set()

    monkeypatch.setattr(gate, "Session", Session)
    monkeypatch.setattr(gate, "acquire", lambda *_: None)
    monkeypatch.setattr(gate, "revoked", lambda *_: False)
    counts = {"prompt_tokens": 11, "completion_tokens": None, "total_tokens": 20}
    failure = (
        CancelledCall(counts)
        if body_error == "cancelled"
        else ProbeError("connection", "controlled", counts=counts)
    )

    async def run():
        async def body():
            async with gate.call_permission(uuid.uuid4(), None):
                if body_error != "none":
                    raise failure

        task = asyncio.create_task(body())
        try:
            assert await asyncio.to_thread(closing.wait, 3)
            task.cancel()
            task.cancel()
        finally:
            release.set()
        result = (await asyncio.gather(task, return_exceptions=True))[0]
        assert closed.is_set(), "permission cleanup must finish before propagation"
        if body_error == "none":
            assert isinstance(result, asyncio.CancelledError)
        elif body_error == "provider":
            assert result is failure and result.counts == counts
        else:
            # gather normalizes cancelled tasks; catch inside an outer coroutine
            # below to retain the actual exception object for the assertion.
            assert isinstance(result, asyncio.CancelledError)

    if body_error != "cancelled":
        asyncio.run(run())
        return

    async def cancelled_run():
        actual = []

        async def body():
            try:
                async with gate.call_permission(uuid.uuid4(), None):
                    raise failure
            except asyncio.CancelledError as error:
                actual.append(error)

        task = asyncio.create_task(body())
        try:
            assert await asyncio.to_thread(closing.wait, 3)
            task.cancel()
            task.cancel()
        finally:
            release.set()
        await task
        assert closed.is_set()
        assert actual == [failure] and actual[0].counts == counts

    asyncio.run(cancelled_run())


def test_cancelled_acquisition_finishes_before_session_close(monkeypatch):
    entered, release, acquired, closed = Event(), Event(), Event(), Event()
    order = []

    class Session:
        def __init__(self, *_):
            pass

        def close(self):
            order.append("close")
            closed.set()

    def acquire(*_):
        entered.set()
        assert release.wait(5)
        order.append("acquired")
        acquired.set()
        return None

    monkeypatch.setattr(gate, "Session", Session)
    monkeypatch.setattr(gate, "acquire", acquire)

    async def run():
        async def body():
            async with gate.call_permission(uuid.uuid4(), None):
                raise AssertionError("cancelled waiter must not enter the body")

        task = asyncio.create_task(body())
        assert await asyncio.to_thread(entered.wait, 3)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        release.set()
        result = (await asyncio.gather(task, return_exceptions=True))[0]
        assert isinstance(result, asyncio.CancelledError)
        assert acquired.is_set() and closed.is_set()
        assert order == ["acquired", "close"]

    asyncio.run(run())
