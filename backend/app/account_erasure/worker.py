import asyncio
import uuid

from app.account_erasure.service import purge
from app.training.queue import queue


@queue.task(name="account.erase")
async def erase_account(user_id: str) -> None:
    await asyncio.to_thread(purge, uuid.UUID(user_id))
