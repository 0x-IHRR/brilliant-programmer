import base64
import json
import secrets
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException
from pydantic import SecretStr
from sqlmodel import Session, select

from app.core.config import settings
from app.model_config.models import ModelConfig
from app.models import User


def lock_owner(session: Session, user_id: uuid.UUID) -> User:
    user = session.exec(
        select(User).where(User.id == user_id).with_for_update()
    ).one_or_none()
    if not user or not user.is_active or not user.email_verified:
        raise HTTPException(403, "账号不可用或邮箱尚未验证")
    return user


def cipher(version: str) -> AESGCM:
    try:
        encoded = settings.MODEL_ENCRYPTION_KEYS[version].get_secret_value()
        key = base64.b64decode(encoded, validate=True)
        if len(key) != 32:
            raise ValueError
        return AESGCM(key)
    except KeyError, ValueError:
        raise HTTPException(503, "模型凭据加密材料不可用，请联系运营者")


def binding(config: ModelConfig) -> bytes:
    return json.dumps(
        [
            str(config.user_id),
            str(config.version),
            config.service_url,
            config.model_id,
            config.key_version,
        ],
        separators=(",", ":"),
    ).encode()


def encrypt(config: ModelConfig, key: SecretStr) -> bytes:
    nonce = secrets.token_bytes(12)
    return nonce + cipher(config.key_version).encrypt(
        nonce, key.get_secret_value().encode(), binding(config)
    )


def decrypt(config: ModelConfig) -> SecretStr:
    try:
        return SecretStr(
            cipher(config.key_version)
            .decrypt(
                config.encrypted_key[:12], config.encrypted_key[12:], binding(config)
            )
            .decode()
        )
    except InvalidTag, ValueError, UnicodeError:
        raise HTTPException(503, "模型凭据无法解密，请联系运营者或重新填写 Key")


@contextmanager
def credential_for_call(
    session: Session,
    user_id: uuid.UUID,
    version: uuid.UUID,
) -> Iterator[tuple[ModelConfig, SecretStr]]:
    """Use inside an isolated transaction; never cache yielded plaintext.

    user_id must come from server authentication or verified persisted job ownership,
    never an arbitrary request field.
    Caller must perform each actual request inside this context and validate its
    destination. Jobs persist only owner/version, never the returned credential.
    """
    # ponytail: per-user lock spans one request (caller timeout <=120s); #15 adds cancellable dispatch.
    lock_owner(session, user_id)
    config = session.get(ModelConfig, user_id, populate_existing=True)
    if not config or config.version != version:
        raise HTTPException(409, "模型配置已删除或变更，请使用当前配置主动重试")
    yield config, decrypt(config)
