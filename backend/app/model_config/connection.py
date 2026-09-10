"""Explicit, bounded OpenAI-compatible probes. No saved credential is read here."""

import asyncio
import ipaddress
import json
import logging
import socket
import ssl
from collections.abc import Iterable
from typing import Any, Literal

import httpcore
from pydantic import BaseModel, Field, SecretStr

from app.model_config.models import ModelConfigFields, validate_service_url

ATTEMPT_SECONDS = 120
MAX_BYTES = 1024 * 1024
BACKOFF_SECONDS = (1, 2)
# Transport DEBUG output includes untrusted response headers, which may echo a Key.
logging.getLogger("httpcore").setLevel(logging.WARNING)
SocketOption = (
    tuple[int, int, int]
    | tuple[int, int, bytes | bytearray]
    | tuple[int, int, None, int]
)


class ProbeInput(ModelConfigFields):
    # The draft never falls back to a stored Key. List requests need no model ID.
    model_id: str = Field(default="", max_length=255)
    api_key: SecretStr
    disclosure_accepted: bool


class Attempt(BaseModel):
    number: int
    code: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class ProbeResult(BaseModel):
    ok: bool
    code: str
    message: str
    models: list[str] = Field(default_factory=list)
    attempts: list[Attempt] = Field(default_factory=list)


class ProbeError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        retry: bool = False,
        counts: dict[str, int | None] | None = None,
    ):
        self.code, self.message, self.retry = code, message, retry
        self.counts = counts if counts is not None else usage(None)
        super().__init__(message)


class CancelledCall(asyncio.CancelledError):
    def __init__(self, counts: dict[str, int | None]):
        self.counts = counts
        super().__init__("model request cancelled")


def public_ip(value: str) -> bool:
    address = ipaddress.ip_address(value)
    if not address.is_global or address.is_multicast:
        return False
    if isinstance(address, ipaddress.IPv6Address):
        # Translation/tunnel addresses can encode a private IPv4 destination.
        return not (
            address.ipv4_mapped
            or address.sixtofour
            or address.teredo
            or address in ipaddress.ip_network("64:ff9b::/96")
            or address in ipaddress.ip_network("64:ff9b:1::/48")
        )
    return True


class PublicBackend(httpcore.AnyIOBackend):
    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[SocketOption] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        from app.account_erasure.outbound import check

        check()
        try:
            answers = await asyncio.get_running_loop().getaddrinfo(
                host, port, type=socket.SOCK_STREAM
            )
        except socket.gaierror as exc:
            raise ProbeError("dns", "服务地址无法解析", exc.errno == socket.EAI_AGAIN)
        addresses = list(dict.fromkeys(answer[4][0] for answer in answers))
        if not addresses or any(not public_ip(ip) for ip in addresses):
            raise ProbeError(
                "unsafe_target", "解析包含非公网或不支持的转换地址，未建立连接"
            )
        # Numeric IP only: no second hostname resolution can rebind this connection.
        # ponytail: first valid address only; add bounded multi-address fallback if needed.
        check()
        stream = await super().connect_tcp(
            addresses[0], port, timeout, local_address, socket_options
        )
        peer = stream.get_extra_info("server_addr")
        if not peer or ipaddress.ip_address(peer[0]) != ipaddress.ip_address(
            addresses[0]
        ):
            await stream.aclose()
            raise ProbeError("unsafe_target", "实际连接目标不匹配，未发送凭据")
        return stream


def usage(value: Any) -> dict[str, int | None]:
    value = value if isinstance(value, dict) else {}
    return {
        name: item
        if type(item := value.get(name)) is int and 0 <= item <= 2**53 - 1
        else None
        for name in ("prompt_tokens", "completion_tokens", "total_tokens")
    }


def received_usage(
    raw: bytes, content_type: str, complete: bool
) -> dict[str, int | None]:
    """Keep only complete provider JSON/ SSE events, even when the reply failed."""
    counts = usage(None)
    if content_type == "application/json":
        events = [raw] if complete else []
    elif content_type == "text/event-stream":
        events = [
            b"\n".join(
                line[5:].lstrip(b" ")
                for line in event.splitlines()
                if line.startswith(b"data:")
            )
            for event in raw.replace(b"\r\n", b"\n").split(b"\n\n")[:-1]
        ]
    else:
        events = []
    for event in events:
        try:
            current = usage(json.loads(event).get("usage"))
        except ValueError, TypeError, AttributeError, RecursionError:
            continue
        counts.update(
            {name: value for name, value in current.items() if value is not None}
        )
    return counts


def parse_reply(
    raw: bytes, content_type: str, listing: bool, key: str
) -> tuple[list[str], dict[str, int | None]]:
    counts = received_usage(raw, content_type, True)
    invalid = ProbeError(
        "invalid_response",
        "服务响应格式无效；可修改配置后主动重试或手填模型 ID",
        counts=counts,
    )
    try:
        text = raw.decode("utf-8")
        if not listing and content_type == "text/event-stream":
            parts: list[str] = []
            done = False
            for event in text.replace("\r\n", "\n").split("\n\n"):
                data = "\n".join(
                    line[5:].lstrip(" ")
                    for line in event.splitlines()
                    if line.startswith("data:")
                )
                if not data:
                    continue
                if done:
                    raise invalid
                if data == "[DONE]":
                    done = True
                    continue
                chunk = json.loads(data)
                choices = chunk["choices"]
                if not isinstance(choices, list):
                    raise invalid
                for choice in choices:
                    if choice.get("index") == 0:
                        content = choice["delta"].get("content")
                        if content is not None:
                            if not isinstance(content, str):
                                raise invalid
                            parts.append(content)
            if not done or not "".join(parts).strip():
                raise invalid
            return [], counts
        if content_type != "application/json":
            raise invalid
        value = json.loads(text)
        if listing:
            entries = value["data"]
            if not isinstance(entries, list) or len(entries) > 2000:
                raise invalid
            models = []
            for entry in entries:
                model = entry["id"]
                if (
                    not isinstance(model, str)
                    or not 1 <= len(model) <= 255
                    or model != model.strip()
                    or any(ord(c) < 32 or ord(c) == 127 for c in model)
                    or key in model
                ):
                    raise invalid
                models.append(model)
            return list(dict.fromkeys(models)), counts
        content = value["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise invalid
        # Do not expose model text: a provider can echo the credential or HTML.
        return [], counts
    except ValueError, KeyError, TypeError, IndexError, AttributeError, RecursionError:
        raise invalid from None


async def request_raw(
    service_url: str, key: str, payload: bytes | None, listing: bool = False
) -> tuple[bytes, str, dict[str, int | None]]:
    """Shared server-only transport; callers own fixed probe or training context."""
    from app.account_erasure.outbound import check

    check()
    base = validate_service_url(service_url)
    raw = bytearray()
    content_type = ""
    complete = False
    try:
        async with asyncio.timeout(ATTEMPT_SECONDS):
            # Direct pool has no environment proxies, redirects, retries or persisted connections.
            async with httpcore.AsyncConnectionPool(
                ssl_context=ssl.create_default_context(),
                network_backend=PublicBackend(),
                retries=0,
            ) as pool:
                async with pool.stream(
                    "GET" if listing else "POST",
                    base + ("/models" if listing else "/chat/completions"),
                    headers={
                        "Authorization": "Bearer " + key,
                        "Content-Type": "application/json",
                        "Accept-Encoding": "identity",
                    },
                    content=payload,
                    extensions={
                        "timeout": dict.fromkeys(
                            ("connect", "read", "write", "pool"), ATTEMPT_SECONDS
                        )
                    },
                ) as response:
                    # These status headers alone are final. Do not wait for an error body.
                    if response.status in (401, 403):
                        raise ProbeError(
                            "authentication",
                            "服务拒绝认证或权限，请检查 Key 与模型权限",
                        )
                    if response.status == 402:
                        raise ProbeError(
                            "balance", "服务报告余额或额度不足，请到服务商核对"
                        )
                    if 300 <= response.status < 400:
                        raise ProbeError(
                            "redirect", "服务返回跳转，未跟随；请核对最终服务地址"
                        )
                    headers = {name.lower(): value for name, value in response.headers}
                    if (
                        headers.get(b"content-encoding", b"identity").lower()
                        != b"identity"
                    ):
                        raise ProbeError("encoding", "服务返回不支持的压缩格式")
                    content_type = (
                        headers.get(b"content-type", b"")
                        .decode("ascii", "replace")
                        .split(";")[0]
                        .strip()
                        .lower()
                    )
                    async for chunk in response.aiter_stream():
                        raw.extend(chunk)
                        if len(raw) > MAX_BYTES:
                            raise ProbeError(
                                "too_large", "服务响应超过 1 MiB，已停止读取"
                            )
                    complete = True
                    if response.status != 200:
                        # Only machine-readable known quota codes influence retries; never echo text.
                        quota = False
                        try:
                            error = json.loads(raw).get("error", {})
                            quota = (
                                error.get("code")
                                in (
                                    "insufficient_quota",
                                    "billing_hard_limit_reached",
                                    "insufficient_balance",
                                )
                                or error.get("type") == "insufficient_quota"
                            )
                        except ValueError, AttributeError, TypeError, RecursionError:
                            pass
                        if quota:
                            raise ProbeError(
                                "balance", "服务报告余额或额度不足，请到服务商核对"
                            )
                        if response.status == 429:
                            raise ProbeError(
                                "rate_limited",
                                "服务限流，有限重试已结束，可稍后主动重试",
                                True,
                            )
                        if response.status in (500, 502, 503, 504):
                            raise ProbeError(
                                "temporary_service",
                                "服务暂时故障，可稍后主动重试",
                                True,
                            )
                        raise ProbeError(
                            "service_rejected",
                            "服务不支持或拒绝本次请求；可检查配置、手填模型 ID",
                        )
                    return (
                        bytes(raw),
                        content_type,
                        received_usage(bytes(raw), content_type, True),
                    )
    except asyncio.CancelledError:
        raise CancelledCall(
            received_usage(bytes(raw[:MAX_BYTES]), content_type, complete)
        ) from None
    except ProbeError as error:
        error.counts = received_usage(bytes(raw[:MAX_BYTES]), content_type, complete)
        raise
    except TimeoutError, httpcore.TimeoutException:
        raise ProbeError(
            "timeout",
            "模型调用超时，可主动重试；已发请求可能计费",
            True,
            counts=received_usage(bytes(raw), content_type, complete),
        ) from None
    except httpcore.ConnectError as exc:
        cause: BaseException | None = exc
        seen: set[int] = set()
        while cause and id(cause) not in seen:
            seen.add(id(cause))
            if isinstance(cause, ssl.SSLError):
                raise ProbeError(
                    "tls", "TLS 证书或握手校验失败，未发送模型请求"
                ) from None
            cause = cause.__cause__ or cause.__context__
        raise ProbeError("connection", "暂时无法连接模型服务", True) from None
    except httpcore.NetworkError, httpcore.ProtocolError:
        raise ProbeError(
            "transport",
            "服务连接中断或协议无效；请检查配置后主动重试",
            counts=received_usage(bytes(raw), content_type, complete),
        ) from None


async def request_once(
    body: ProbeInput, kind: Literal["test", "models"]
) -> tuple[list[str], dict[str, int | None]]:
    listing = kind == "models"
    payload = (
        None
        if listing
        else json.dumps(
            {
                "model": body.model_id,
                "messages": [{"role": "user", "content": "请仅回复 OK"}],
                "stream": False,
            }
        ).encode()
    )
    key = body.api_key.get_secret_value()
    raw, content_type, _counts = await request_raw(
        body.service_url, key, payload, listing
    )
    return parse_reply(raw, content_type, listing, key)
