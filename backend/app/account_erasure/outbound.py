"""Owner identity only; no credential enters account-deletion checks."""

import uuid
from contextvars import ContextVar

owner: ContextVar[uuid.UUID | None] = ContextVar("outbound_account", default=None)


def check() -> None:
    identity = owner.get()
    if identity is not None:
        from app.account_erasure.service import require_account

        require_account(identity)
