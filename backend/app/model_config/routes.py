import asyncio
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import SessionDep, TokenDep, get_current_user, get_training_user
from app.core.config import settings
from app.core.db import engine
from app.model_config.connection import (
    BACKOFF_SECONDS,
    Attempt,
    ProbeError,
    ProbeInput,
    ProbeResult,
    request_once,
)
from app.model_config.models import ModelConfig, ModelConfigPublic, ModelConfigSave
from app.model_config.service import decrypt, encrypt, lock_owner
from app.models import User

router = APIRouter(prefix="/model-config", tags=["modelconfig"])
VerifiedUser = Annotated[User, Depends(get_training_user)]


def public(config: ModelConfig) -> ModelConfigPublic:
    return ModelConfigPublic(
        version=config.version, service_url=config.service_url, model_id=config.model_id
    )


@router.get("")
def read_config(
    session: SessionDep, user: VerifiedUser, response: Response
) -> ModelConfigPublic | None:
    response.headers["Cache-Control"] = "no-store"
    config = session.get(ModelConfig, user.id)
    return public(config) if config else None


@router.put("")
def save_config(
    body: ModelConfigSave, session: SessionDep, user: VerifiedUser, response: Response
) -> ModelConfigPublic:
    response.headers["Cache-Control"] = "no-store"
    lock_owner(session, user.id)
    config = session.get(ModelConfig, user.id, populate_existing=True)
    if (config.version if config else None) != body.expected_version:
        raise HTTPException(409, "配置已变更，请刷新配置后重新编辑")
    if not body.disclosure_accepted:
        raise HTTPException(422, "请确认运营者解密及模型服务接收方告知")
    key = body.api_key
    if key is None:
        if config is None or config.service_url != body.service_url:
            raise HTTPException(422, "首次保存或变更服务地址时必须重新填写 Key")
        key = decrypt(config)
    if config is None:
        config = ModelConfig(
            user_id=user.id,
            service_url=body.service_url,
            model_id=body.model_id,
            encrypted_key=b"",
            key_version=settings.MODEL_ACTIVE_KEY_VERSION,
        )
    config.version = uuid.uuid4()
    config.service_url = body.service_url
    config.model_id = body.model_id
    config.key_version = settings.MODEL_ACTIVE_KEY_VERSION
    config.encrypted_key = encrypt(config, key)
    session.add(config)
    session.commit()
    session.refresh(config)
    return public(config)


@router.delete("", status_code=204)
def delete_config(
    expected_version: uuid.UUID, session: SessionDep, user: VerifiedUser
) -> Response:
    lock_owner(session, user.id)
    config = session.get(ModelConfig, user.id, populate_existing=True)
    if config:
        if config.version != expected_version:
            raise HTTPException(409, "配置已变更，请刷新配置后重新确认删除")
        session.delete(config)
        session.commit()
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


def recheck_caller(token: str) -> None:
    with Session(engine) as session:
        user = get_current_user(session, token)
        get_training_user(user)


@router.post("/probe/{kind}")
async def probe(
    kind: Literal["test", "models"],
    body: ProbeInput,
    token: TokenDep,
    _user: VerifiedUser,
    response: Response,
) -> ProbeResult:
    response.headers["Cache-Control"] = "no-store"
    if not body.disclosure_accepted or (kind == "test" and not body.model_id):
        raise HTTPException(422, "请确认接收方与费用告知；测试连接还须填写模型 ID")
    attempts: list[Attempt] = []
    for index in range(3):
        # Draft requests contain their own Key. Re-check session/owner before every attempt.
        await run_in_threadpool(recheck_caller, token)
        try:
            models, counts = await request_once(body, kind)
        except ProbeError as error:
            attempts.append(Attempt(number=index + 1, code=error.code))
            if error.retry and index < 2:
                await asyncio.sleep(BACKOFF_SECONDS[index])
                continue
            return ProbeResult(
                ok=False, code=error.code, message=error.message, attempts=attempts
            )
        attempts.append(Attempt(number=index + 1, code="ok", **counts))
        return ProbeResult(
            ok=True,
            code="ok" if kind == "test" or models else "empty",
            message="本次调用可用；评分可靠性未验证。未保存配置。"
            if kind == "test"
            else "请选择模型 ID 回填，之后仍需主动保存。"
            if models
            else "服务返回空模型列表，可继续手填模型 ID。",
            models=models,
            attempts=attempts,
        )
    raise AssertionError("bounded attempts must return")
