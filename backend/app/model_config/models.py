import ipaddress
import re
import uuid
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlmodel import Field as DBField
from sqlmodel import SQLModel


def validate_service_url(value: str) -> str:
    """Local syntax checks only; each outbound connection must also validate DNS."""
    try:
        url = urlsplit(value)
        host = url.hostname or ""
        port = url.port
        if (
            url.scheme != "https"
            or not host
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
            or (port is not None and not 1 <= port <= 65535)
            or "\\" in value
            or any(ord(c) <= 32 or ord(c) >= 127 for c in value)
            or "%" in host
            or host.endswith(".")
        ):
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if (
                "." not in host
                or host.endswith((".local", ".localhost", ".internal", ".test"))
                or not re.fullmatch(r"[a-zA-Z0-9.-]+", host)
                or any(
                    not label
                    or label.startswith("-")
                    or label.endswith("-")
                    or len(label) > 63
                    for label in host.split(".")
                )
            ):
                raise ValueError
        else:
            if not address.is_global:
                raise ValueError
    except ValueError:
        raise ValueError(
            "服务地址须为公网 HTTPS 地址（端口 1–65535），不能含账号、查询或片段"
        )
    return value.rstrip("/")


class ModelConfig(SQLModel, table=True):
    __tablename__ = "model_config"
    user_id: uuid.UUID = DBField(foreign_key="user.id", primary_key=True)
    version: uuid.UUID = DBField(default_factory=uuid.uuid4, unique=True)
    service_url: str
    model_id: str
    encrypted_key: bytes = DBField(repr=False)
    key_version: str


class ModelConfigSave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service_url: str = Field(min_length=1, max_length=2048)
    model_id: str = Field(min_length=1, max_length=255)
    api_key: SecretStr | None = None
    expected_version: uuid.UUID | None = None
    disclosure_accepted: bool

    @field_validator("service_url")
    @classmethod
    def service(cls, value: str) -> str:
        return validate_service_url(value)

    @field_validator("model_id")
    @classmethod
    def model_name(cls, value: str) -> str:
        if value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("模型 ID 不能含首尾空白或控制字符")
        return value

    @field_validator("api_key")
    @classmethod
    def key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            raw = value.get_secret_value()
            if not 1 <= len(raw) <= 4096 or any(
                ord(c) < 33 or ord(c) > 126 for c in raw
            ):
                raise ValueError("Key 须为 1–4096 个可打印 ASCII 字符且不含空白")
        return value


class ModelConfigPublic(BaseModel):
    version: uuid.UUID
    service_url: str
    model_id: str
    has_key: bool = True
