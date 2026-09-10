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
    from app.account_erasure.service import denied

    try:
        if denied(user_id):
            return True
    except HTTPException:
        return True
    with Session(engine) as session:
        config = session.get(ModelConfig, user_id)
        return (config.version if config else None) != version or bool(
            config and config.revoked
        )


def acquire(
    session: Session, user_id: uuid.UUID, version: uuid.UUID | None
) -> ModelConfig | None:
    from app.account_erasure.service import require_ready

    require_ready(session)
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
    from app.account_erasure.outbound import owner

    owner_token = owner.set(user_id)
    failure: BaseException | None = None

    async def watch() -> None:
        while True:
            if await asyncio.to_thread(revoked, user_id, version):
                assert caller
                caller.cancel()
                return
            await asyncio.sleep(0.1)

    try:
        config = await asyncio.shield(acquisition)
        # The synchronous acquire may have finished before its awaiter resumes.
        # Recheck durable account intent before exposing this permission to HTTP.
        from app.account_erasure.service import require_account

        require_account(user_id)
        watcher = asyncio.create_task(watch())
        yield config
    except BaseException as error:
        # Includes CancelledCall/ProbeError with already received usage. A later
        # cancellation during cleanup must not replace this original evidence.
        failure = error
        raise
    finally:
        async def release() -> None:
            if watcher:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
            # to_thread cannot be stopped by cancelling its awaiter. Wait for
            # acquisition before closing, including repeatedly cancelled waiters.
            await asyncio.gather(acquisition, return_exceptions=True)
            await asyncio.to_thread(session.close)

        cleanup = asyncio.create_task(release())
        interrupted: asyncio.CancelledError | None = None
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError as error:
                interrupted = error
        owner.reset(owner_token)
        cleanup.result()  # Cleanup failures must remain visible.
        if interrupted is not None and failure is None:
            # A successful body does not swallow a cancellation during cleanup.
            raise interrupted


@asynccontextmanager
async def call_credential(
    user_id: uuid.UUID, version: uuid.UUID
) -> AsyncIterator[tuple[ModelConfig, SecretStr]]:
    async with call_permission(user_id, version) as config:
        assert config
        yield config, decrypt(config)
