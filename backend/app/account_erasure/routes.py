import uuid
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.account_erasure import service
from app.account_erasure.models import AccountErasure
from app.api.deps import CurrentUser, SessionDep
from app.api.rate_limit import protect_auth

router = APIRouter(prefix="/account-erasure", tags=["account-erasure"], dependencies=[Depends(protect_auth)])


class Password(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: SecretStr = Field(min_length=1, max_length=128)


class ReceiptKey(BaseModel):
    model_config = ConfigDict(extra="forbid")
    receipt_key: SecretStr = Field(min_length=43, max_length=43)


class Confirmation(ReceiptKey):
    confirmation: Literal["注销本账号并永久删除全部私有资料"]


class Status(BaseModel):
    request_id: uuid.UUID
    accepted_at: datetime | None
    completed_at: datetime | None
    online_deadline: datetime | None
    backup_deadline: datetime | None


class Preview(Status):
    receipt_key: str
    expires_at: datetime
    records: dict[str, int]
    consequences: list[str]


def public(item: AccountErasure) -> Status:
    return Status(request_id=item.request_id, accepted_at=item.accepted_at, completed_at=item.completed_at,
        online_deadline=item.accepted_at + timedelta(hours=24) if item.accepted_at else None,
        backup_deadline=item.accepted_at + timedelta(days=30) if item.accepted_at else None)


@router.post("/preview")
def preview(body: Password, user: CurrentUser, session: SessionDep, response: Response) -> Preview:
    response.headers["Cache-Control"] = "no-store"
    item, secret, counts = service.preview(session, user.id, body.password.get_secret_value())
    return Preview(**public(item).model_dump(), receipt_key=secret, expires_at=item.expires_at, records=counts, consequences=[
        "注销本账号全部私有资料，含确认前新保存的数据；数量只作预览，不限定本次全账号范围。",
        "确认后立即禁止登录、旧会话及新模型调用；在线账号、Key、草稿、学习与成长档案在24小时内清除，不保留等级或奖励档案。",
        "仅保留无原文的注销身份和时点，独立删除日志用于旧备份恢复重放；备份最长30天退出。受控演练不代表生产备份服务已经配置。",
        "其他账号及其仍有效引用的公共附件不受影响。决定不可撤销，不通过管理员恢复或转移旧记录。",
    ])


@router.post("/{request_id}/confirm", status_code=202)
def confirm(request_id: uuid.UUID, body: Confirmation, session: SessionDep, response: Response) -> Status:
    response.headers["Cache-Control"] = "no-store"
    item = service.confirm(session, request_id, body.receipt_key.get_secret_value())
    service.drain_permission(session, item)
    return public(item)


@router.post("/{request_id}/status")
def status(request_id: uuid.UUID, body: ReceiptKey, session: SessionDep, response: Response) -> Status:
    response.headers["Cache-Control"] = "no-store"
    return public(service.receipt(session, request_id, body.receipt_key.get_secret_value()))
