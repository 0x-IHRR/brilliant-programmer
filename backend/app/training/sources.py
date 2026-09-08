"""Read-only public reference acquisition. No repository code is executed."""

import asyncio
import hashlib
import re
import ssl
from html.parser import HTMLParser

import httpcore

from app.model_config.connection import MAX_BYTES, ProbeError, PublicBackend
from app.training.schema import Source

# Release-owned starting references, not a question bank or a claim of human approval.
REFERENCES = {
    "requirements": "https://www.w3.org/WAI/WCAG22/Understanding/keyboard.html",
    "systems": "https://docs.python.org/3.14/tutorial/controlflow.html",
    "frontend": "https://www.w3.org/WAI/WCAG22/Understanding/keyboard.html",
    "network": "https://www.rfc-editor.org/rfc/rfc9110.txt",
    "api": "https://www.rfc-editor.org/rfc/rfc9110.txt",
    "data": "https://www.postgresql.org/docs/17/ddl-constraints.html",
    "async": "https://www.rabbitmq.com/docs/confirms",
    "testing": "https://docs.python.org/3.14/library/unittest.html",
    "performance": "https://www.postgresql.org/docs/17/using-explain.html",
    "security": "https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html",
    "operations": "https://www.postgresql.org/docs/17/backup-dump.html",
    "architecture": "https://www.postgresql.org/docs/17/tutorial-arch.html",
    "ai": "https://www.nist.gov/itl/ai-risk-management-framework",
    "team": "https://git-scm.com/docs/git-diff",
}


class PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "nav", "header", "footer"}:
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "nav", "header", "footer"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data: str) -> None:
        if not self.hidden and data.strip():
            self.parts.append(data.strip())


async def acquire_source(capability_id: str) -> list[Source]:
    url = REFERENCES[capability_id.split(".")[0]]
    try:
        async with asyncio.timeout(30):
            async with httpcore.AsyncConnectionPool(
                ssl_context=ssl.create_default_context(),
                network_backend=PublicBackend(),
                retries=0,
            ) as pool:
                async with pool.stream(
                    "GET", url, headers={"Accept-Encoding": "identity"}
                ) as response:
                    if response.status != 200:
                        raise ProbeError(
                            "source_unavailable",
                            "公开依据无法读取，未生成案例；可更换方向",
                        )
                    raw = bytearray()
                    async for chunk in response.aiter_stream():
                        raw.extend(chunk)
                        if len(raw) > MAX_BYTES:
                            raise ProbeError(
                                "source_too_large",
                                "公开依据超过读取上限，未生成案例；可更换方向",
                            )
        text = raw.decode("utf-8")
        if "<html" in text[:1000].lower() or "<!doctype" in text[:1000].lower():
            parser = PlainText()
            parser.feed(text)
            text = "\n".join(parser.parts)
        # Keep a verifiable bounded snapshot. A content hash pins the fetched version.
        offset = 0
        if url.endswith("rfc9110.txt"):
            marker = (
                "9.2.2.  Idempotent Methods"
                if capability_id.endswith(("delivery", "idempotency"))
                else "15.5.2.  401 Unauthorized"
            )
            offset = max(0, text.rfind(marker))
        text = text[offset : offset + 6000]
        if re.search(
            r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bAKIA[A-Z0-9]{16}\b|\bsk-[A-Za-z0-9_-]{24,}",
            text,
        ):
            raise ProbeError(
                "source_secret", "必要公开片段疑似包含秘密，未发送；请更换方向"
            )
        if len(text.strip()) < 100:
            raise ValueError
        return [
            Source(
                id="reference-1",
                url=url,
                version="sha256:" + hashlib.sha256(bytes(raw)).hexdigest(),
                locator=f"响应正文提取文本字符{offset}–{offset + len(text)}（完整响应SHA-256；本次抓取版本，不冒充官方版本号）",
                text=text,
            )
        ]
    except ProbeError:
        raise
    except (
        TimeoutError,
        httpcore.NetworkError,
        httpcore.ProtocolError,
        httpcore.TimeoutException,
        UnicodeError,
        ValueError,
    ):
        raise ProbeError(
            "source_unavailable", "公开依据无法安全读取，未生成案例；可更换方向"
        ) from None
