import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from app.api.deps import SessionDep, get_training_user
from app.core.config import settings
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
