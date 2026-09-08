"""Keep the existing credential lock across a request without blocking asyncio."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from pydantic import SecretStr
from sqlmodel import Session

from app.core.db import engine
from app.model_config.models import ModelConfig
from app.model_config.service import credential_for_call


@asynccontextmanager
async def call_credential(
    user_id: uuid.UUID, version: uuid.UUID
) -> AsyncIterator[tuple[ModelConfig, SecretStr]]:
    session = Session(engine)
    context = credential_for_call(session, user_id, version)
    acquisition = asyncio.create_task(asyncio.to_thread(context.__enter__))
    entered = False
    try:
        try:
            credential = await asyncio.shield(acquisition)
            entered = True
        except asyncio.CancelledError:
            # A cancelled waiter must still release a lock its thread later acquires.
            await acquisition
            entered = True
            raise
        yield credential
    finally:
        if entered:
            await asyncio.to_thread(context.__exit__, None, None, None)
        await asyncio.to_thread(session.close)
