"""Hold dispatch permission through HTTP, cancellable by persisted config intent."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import HTTPException
from pydantic import SecretStr
from sqlmodel import Session

from app.core.db import engine
from app.model_config.models import ModelConfig
from app.model_config.service import decrypt, lock_owner


def revoked(user_id: uuid.UUID, version: uuid.UUID | None) -> bool:
    with Session(engine) as session:
        config = session.get(ModelConfig, user_id)
        return (config.version if config else None) != version or bool(
            config and config.revoked
        )


def acquire(
    session: Session, user_id: uuid.UUID, version: uuid.UUID | None
) -> ModelConfig | None:
    lock_owner(session, user_id)
    config = session.get(ModelConfig, user_id, populate_existing=True)
    if (config.version if config else None) != version or (config and config.revoked):
        raise HTTPException(409, "模型配置已撤销或变更，请主动重试")
    return config


@asynccontextmanager
async def call_permission(
    user_id: uuid.UUID, version: uuid.UUID | None
) -> AsyncIterator[ModelConfig | None]:
    """Also guards draft probes without decrypting the saved credential."""
    session = Session(engine)
    acquisition = asyncio.create_task(
        asyncio.to_thread(acquire, session, user_id, version)
    )
    watcher: asyncio.Task[None] | None = None
    caller = asyncio.current_task()

    async def watch() -> None:
        while True:
            if await asyncio.to_thread(revoked, user_id, version):
                assert caller
                caller.cancel()
                return
            await asyncio.sleep(0.1)

    try:
        try:
            config = await asyncio.shield(acquisition)
        except asyncio.CancelledError:
            # A cancelled waiter must release a lock its thread later acquires.
            await acquisition
            raise
        watcher = asyncio.create_task(watch())
        yield config
    finally:
        if watcher:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        await asyncio.to_thread(session.close)


@asynccontextmanager
async def call_credential(
    user_id: uuid.UUID, version: uuid.UUID
) -> AsyncIterator[tuple[ModelConfig, SecretStr]]:
    async with call_permission(user_id, version) as config:
        assert config
        yield config, decrypt(config)
