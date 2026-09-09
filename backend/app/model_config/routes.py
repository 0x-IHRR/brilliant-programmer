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
    CancelledCall,
    ProbeError,
    ProbeInput,
    ProbeResult,
    request_once,
)
from app.model_config.models import ModelConfig, ModelConfigPublic, ModelConfigSave
from app.model_config.revocation import request_revocation, stop_old_tasks
from app.model_config.service import decrypt, encrypt, lock_owner
from app.model_config.usage import UsageReport, record_probe, report, start_probe
from app.models import User
from app.training.gate import call_permission

router = APIRouter(prefix="/model-config", tags=["modelconfig"])
VerifiedUser = Annotated[User, Depends(get_training_user)]


def public(config: ModelConfig, session: Session) -> ModelConfigPublic:
    from app.quality.public import describe
    from app.quality.rules import Binding
    from app.training.evaluation_schema import EVALUATION_RULE

    return ModelConfigPublic(
        quality=describe(
            session,
            Binding(
                user_id=config.user_id,
                config_version=config.version,
                destination=config.service_url,
                model_id=config.model_id,
                evaluation_rule=EVALUATION_RULE,
            ),
        ),
        version=config.version,
        service_url=config.service_url,
        model_id=config.model_id,
        revoked=config.revoked,
    )


@router.get("")
def read_config(
    session: SessionDep, user: VerifiedUser, response: Response
) -> ModelConfigPublic | None:
    response.headers["Cache-Control"] = "no-store"
    config = session.get(ModelConfig, user.id)
    return public(config, session) if config else None


@router.get("/usage")
def read_usage(
    session: SessionDep, user: VerifiedUser, response: Response
) -> UsageReport:
    response.headers["Cache-Control"] = "no-store"
    return report(session, user.id)


@router.put("")
def save_config(
    body: ModelConfigSave, session: SessionDep, user: VerifiedUser, response: Response
) -> ModelConfigPublic:
    response.headers["Cache-Control"] = "no-store"
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
    replacement = ModelConfig(
        user_id=user.id,
        service_url=body.service_url,
        model_id=body.model_id,
        encrypted_key=b"",
        key_version=settings.MODEL_ACTIVE_KEY_VERSION,
    )
    replacement.encrypted_key = encrypt(replacement, key)
    if body.expected_version:
        request_revocation(user.id, body.expected_version)
    lock_owner(session, user.id)
    config = session.get(ModelConfig, user.id, populate_existing=True)
    if (config.version if config else None) != body.expected_version:
        raise HTTPException(409, "配置已变更，请刷新后重新编辑；未覆盖新版本")
    if body.expected_version:
        stop_old_tasks(session, user.id, body.expected_version)
    config = session.merge(replacement)
    session.commit()
    session.refresh(config)
    return public(config, session)


@router.delete("", status_code=204)
def delete_config(
    expected_version: uuid.UUID, session: SessionDep, user: VerifiedUser
) -> Response:
    config = session.get(ModelConfig, user.id)
    if config:
        request_revocation(user.id, expected_version)
    lock_owner(session, user.id)
    config = session.get(ModelConfig, user.id, populate_existing=True)
    if config:
        if config.version != expected_version:
            raise HTTPException(409, "配置已变更，请刷新配置后重新确认删除")
        stop_old_tasks(session, user.id, expected_version)
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
    with Session(engine) as session:
        config = session.get(ModelConfig, _user.id)
        version = config.version if config else None
    operation_id = uuid.uuid4()
    attempts: list[Attempt] = []
    for index in range(3):
        # Draft requests contain their own Key. Re-check session/owner before every attempt.
        await run_in_threadpool(recheck_caller, token)
        identity = await run_in_threadpool(
            start_probe,
            _user.id,
            operation_id,
            index + 1,
            kind,
            body.service_url,
            body.model_id,
        )
        counts: dict[str, int | None] = {}
        try:
            async with call_permission(_user.id, version):
                await run_in_threadpool(record_probe, identity, "unknown", {})
                models, counts = await request_once(body, kind)
        except asyncio.CancelledError as error:
            counts = error.counts if isinstance(error, CancelledCall) else counts
            await run_in_threadpool(record_probe, identity, "cancelled", counts)
            attempts.append(Attempt(number=index + 1, code="cancelled", **counts))
            return ProbeResult(
                ok=False,
                code="cancelled",
                message="本次测试/列表已取消，旧结果不回填；在途可能收费。",
                attempts=attempts,
            )
        except HTTPException:
            return ProbeResult(
                ok=False,
                code="configuration_revoked",
                message="配置已变更或撤销，未继续测试/列表；请主动重试。",
                attempts=attempts,
            )
        except ProbeError as error:
            await run_in_threadpool(record_probe, identity, error.code, error.counts)
            attempts.append(Attempt(number=index + 1, code=error.code, **error.counts))
            if error.retry and index < 2:
                await asyncio.sleep(BACKOFF_SECONDS[index])
                continue
            return ProbeResult(
                ok=False, code=error.code, message=error.message, attempts=attempts
            )
        await run_in_threadpool(record_probe, identity, "ok", counts)
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
