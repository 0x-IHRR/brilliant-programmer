"""Anonymous GitHub REST reads only; never clone, execute, or follow a link."""

import asyncio
import base64
import hashlib
import json
import re
import ssl
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from typing import Any
from urllib.parse import quote, unquote, urlsplit

import httpcore

from app.model_config.connection import ProbeError, PublicBackend
from app.project.schema import FileEntry, Fragment, Repository

MAX_RESPONSE = 2 * 1024 * 1024
MAX_BLOB_BYTES = 1024 * 1024
MAX_REQUESTS = 48
MAX_FILES = 16
MAX_FRAGMENT_BYTES = 24 * 1024
MAX_ENTRIES = 3000
SKIP_PARTS = {
    "node_modules",
    "vendor",
    ".git",
    ".venv",
    "venv",
    "dist",
    "build",
    "__pycache__",
    "coverage",
}
SECRET = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bAKIA[A-Z0-9]{16}\b|"
    r"\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]{20,}|"
    r"(?i:(?:api[_-]?key|password|secret|access[_-]?token)\s*[:=]\s*['\"][^'\"\s]{12,}['\"])"
)


def safe_path(path: str) -> bool:
    return bool(path) and not any(
        part in {"", ".", ".."}
        or "\\" in part
        or any(ord(c) < 32 or ord(c) == 127 for c in part)
        for part in path.split("/")
    )


def parse_url(url: str) -> tuple[str, str, str, str]:
    """Parse syntax only. Ref/path boundaries must come from repository facts."""
    if (
        len(url) > 2048
        or url != url.strip()
        or any(ord(c) < 33 or ord(c) == 127 for c in url)
    ):
        raise ValueError("invalid GitHub URL")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() != "github.com"
        or parsed.query
    ):
        raise ValueError("public github.com HTTPS required")
    path = unquote(parsed.path, errors="strict").strip("/")
    if not safe_path(path) or "%" in path:
        raise ValueError("invalid path")
    parts = path.split("/")
    if len(parts) < 2 or not re.fullmatch(r"[A-Za-z0-9-]{1,39}", parts[0]):
        raise ValueError("invalid owner")
    owner, name = parts[:2]
    name = name.removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", name) or name in {".", ".."}:
        raise ValueError("invalid repository")
    if len(parts) == 2:
        return owner, name, "", ""
    if parts[2] not in {"tree", "blob", "commit"} or len(parts) < 4:
        raise ValueError("unsupported GitHub link")
    if parsed.fragment and not re.fullmatch(r"L\d+(?:-L\d+)?", parsed.fragment):
        raise ValueError("invalid source lines")
    return owner, name, parts[2], "/".join(parts[3:])


class GitHub:
    def __init__(
        self, authorize: Callable[[], AbstractAsyncContextManager[None]] | None = None
    ) -> None:
        self.requests = 0
        self.bytes = 0
        self.authorize = authorize

    async def get(self, path: str) -> Any:
        async with AsyncExitStack() as stack:
            if self.authorize is not None:
                await stack.enter_async_context(self.authorize())
            return await self._get(path)

    async def _get(self, path: str) -> Any:
        if self.requests >= MAX_REQUESTS:
            raise ProbeError(
                "github_scope", "本次 GitHub 请求范围已用尽；已核对成果保留"
            )
        self.requests += 1
        try:
            async with asyncio.timeout(30):
                async with httpcore.AsyncConnectionPool(
                    ssl_context=ssl.create_default_context(),
                    network_backend=PublicBackend(),
                    retries=0,
                ) as pool:
                    async with pool.stream(
                        "GET",
                        "https://api.github.com" + path,
                        headers={
                            "Accept": "application/vnd.github+json",
                            "Accept-Encoding": "identity",
                            "User-Agent": "brilliant-programmer-project-map",
                            "X-GitHub-Api-Version": "2022-11-28",
                        },
                    ) as response:
                        headers = {
                            key.lower(): value for key, value in response.headers
                        }
                        if response.status == 429 or (
                            response.status == 403
                            and (
                                headers.get(b"x-ratelimit-remaining") == b"0"
                                or b"retry-after" in headers
                            )
                        ):
                            raise ProbeError(
                                "github_rate_limited",
                                "GitHub 限流；请稍后主动重试，已核对成果保留",
                            )
                        if response.status == 404:
                            raise ProbeError(
                                "github_unavailable",
                                "当前无法匿名读取；可能与访问权限、仓库状态有关，不能据此确定私有或不存在",
                            )
                        if response.status != 200:
                            raise ProbeError(
                                "github_unavailable",
                                "GitHub 当前无法读取或要求跳转；未跟随跳转，已核对成果保留",
                            )
                        if (
                            headers.get(b"content-encoding", b"identity").lower()
                            != b"identity"
                        ):
                            raise ProbeError(
                                "github_encoding",
                                "GitHub 返回不支持的压缩内容，已停止读取",
                            )
                        data = bytearray()
                        async for chunk in response.aiter_stream():
                            self.bytes += len(chunk)
                            data.extend(chunk)
                            if len(data) > MAX_RESPONSE:
                                raise ProbeError(
                                    "github_scope",
                                    "响应超出本次已验证读取范围，已停止；已核对成果保留",
                                )
                        return json.loads(data)
        except ProbeError:
            raise
        except (
            TimeoutError,
            httpcore.NetworkError,
            httpcore.ProtocolError,
            httpcore.TimeoutException,
            ValueError,
            RecursionError,
        ):
            raise ProbeError(
                "github_unavailable", "GitHub 无法安全读取；已核对成果保留，可主动重试"
            ) from None

    async def resolve(self, url: str) -> Repository:
        owner, name, kind, tail = parse_url(url)
        base = f"/repos/{owner}/{name}"
        metadata = await self.get(base)
        try:
            if metadata["private"] is not False:
                raise ProbeError(
                    "github_private", "GitHub 标识该仓库为私有；首版不接入私有仓库"
                )
            ref, focus = metadata["default_branch"], ""
            resolved = None
            if not kind:
                resolved = (
                    await self.get(base + "/git/ref/heads/" + quote(ref, safe=""))
                )["object"]
            if kind == "commit":
                if not re.fullmatch(r"[0-9a-fA-F]{7,40}", tail):
                    raise ValueError
                ref = tail
            elif kind:
                first = quote(tail.split("/")[0], safe="")
                candidates: list[tuple[str, dict[str, Any]]] = []
                for namespace in ("heads", "tags"):
                    refs = await self.get(
                        base + f"/git/matching-refs/{namespace}/{first}"
                    )
                    for item in refs:
                        actual = item["ref"].removeprefix(f"refs/{namespace}/")
                        if actual == tail or tail.startswith(actual + "/"):
                            candidates.append((actual, item["object"]))
                if len(candidates) > 1:
                    raise ProbeError(
                        "github_ambiguous_ref",
                        "仓库存在多个匹配的 ref，请使用明确 commit 链接消除歧义",
                    )
                if candidates:
                    ref, resolved = candidates[0]
                    focus = tail[len(ref) :].lstrip("/")
                elif re.fullmatch(r"[0-9a-fA-F]{7,40}", tail.split("/")[0]):
                    ref, _, focus = tail.partition("/")
                else:
                    raise ProbeError(
                        "github_ref_missing",
                        "仓库事实中未找到该版本；请核对分支、标签或提交链接",
                    )
                if kind == "blob" and not focus:
                    raise ValueError
            if resolved:
                # An annotated tag may point to another tag. Never treat its object SHA as a commit.
                while resolved["type"] == "tag":
                    resolved = (
                        await self.get(
                            base + "/git/tags/" + quote(resolved["sha"], safe="")
                        )
                    )["object"]
                if resolved["type"] != "commit":
                    raise ValueError
            commit = await self.get(
                base
                + "/commits/"
                + quote(resolved["sha"] if resolved else ref, safe="")
            )
            start_line, end_line = 1, None
            anchor = urlsplit(url).fragment
            if kind == "blob" and anchor:
                first, _, last = anchor.partition("-L")
                start_line = int(first.removeprefix("L"))
                end_line = int(last) if last else start_line
                if end_line < start_line:
                    raise ValueError
            repository = Repository(
                owner=owner,
                name=name,
                commit=commit["sha"],
                tree=commit["commit"]["tree"]["sha"],
                ref=ref,
                focus=focus,
                start_line=start_line,
                end_line=end_line,
            )
            if focus:
                # Validate the path by walking this pinned commit's actual tree; no contents symlink dereference.
                tree = repository.tree
                for index, part in enumerate(focus.split("/")):
                    entries = await self.directory(repository, tree)
                    entry = next(
                        (entry for entry in entries if entry.path == part), None
                    )
                    if not entry or entry.mode == "120000" or entry.kind == "commit":
                        raise ProbeError(
                            "github_path_missing",
                            "固定版本中未找到可安全读取的目标路径",
                        )
                    if index < len(focus.split("/")) - 1 and entry.kind != "tree":
                        raise ValueError
                    tree = entry.sha
                if kind == "blob" and entry and entry.kind != "blob":
                    raise ValueError
            return repository
        except KeyError, TypeError, ValueError, AttributeError:
            raise ProbeError(
                "github_invalid", "GitHub 版本或路径响应无效，未猜测版本"
            ) from None

    async def directory(
        self, repository: Repository, tree: str, prefix: str = ""
    ) -> list[FileEntry]:
        value = await self.get(
            f"/repos/{repository.owner}/{repository.name}/git/trees/{tree}"
        )
        try:
            if value.get("truncated") or len(value["tree"]) > MAX_ENTRIES:
                raise ProbeError(
                    "github_scope", "目录超过已验证范围；未读取的路径保持未核实"
                )
            entries = []
            for item in value["tree"]:
                path = item["path"]
                if not safe_path(path) or "/" in path:
                    raise ValueError
                entries.append(
                    FileEntry(
                        path=prefix + path,
                        sha=item["sha"],
                        kind=item["type"],
                        mode=item["mode"],
                        size=item.get("size", 0),
                    )
                )
            return entries
        except KeyError, TypeError, ValueError, AttributeError:
            raise ProbeError("github_invalid", "目录响应无效，未继续读取") from None

    async def fragment(
        self,
        repository: Repository,
        entry: FileEntry,
        *,
        start: int = 1,
        end: int | None = None,
    ) -> Fragment:
        if entry.kind != "blob" or entry.mode not in {"100644", "100755"}:
            raise ProbeError("github_skipped", "符号链接与子模块只记目录，不读取目标")
        if entry.size > MAX_BLOB_BYTES:
            raise ProbeError(
                "github_scope",
                "文件超过 1 MiB 已验证范围，未读取；请提供较小的必要文本范围",
            )
        value = await self.get(
            f"/repos/{repository.owner}/{repository.name}/git/blobs/{entry.sha}"
        )
        try:
            if value["encoding"] != "base64":
                raise ValueError
            data = base64.b64decode(value["content"].replace("\n", ""), validate=True)
            # Git blob identity binds every fragment to the tree in the pinned commit.
            if (
                len(data) != entry.size
                or hashlib.sha1(
                    b"blob " + str(len(data)).encode() + b"\0" + data
                ).hexdigest()
                != entry.sha
            ):
                raise ValueError
            if b"\0" in data:
                raise ProbeError("github_binary", "二进制文件不读取或发给模型")
            text = data.decode("utf-8")
            if any(ord(c) < 32 and c not in "\n\r\t" for c in text):
                raise ProbeError("github_binary", "非文本内容未纳入分析")
            if SECRET.search(text):
                raise ProbeError(
                    "source_secret",
                    "文件疑似包含秘密，已排除；请提供脱敏版本，检测不保证零漏报",
                )
            # Preserve complete lines only, with a verifiable range, never a permanent full-repo download.
            all_lines = text.splitlines()
            if (
                start < 1
                or start > len(all_lines)
                or (end is not None and not start <= end <= len(all_lines))
            ):
                raise ProbeError(
                    "github_range", "指定行范围在固定版本中不可读取，未猜测或替换来源"
                )
            lines, size = [], 0
            for line in all_lines[start - 1 : end]:
                size += len(line.encode()) + 1
                if size > MAX_FRAGMENT_BYTES:
                    break
                lines.append(line)
            if not lines:
                raise ProbeError(
                    "github_scope", "文件为空或单行超过已验证范围，未纳入分析"
                )
            return Fragment(
                path=entry.path,
                blob=entry.sha,
                start=start,
                end=start + len(lines) - 1,
                total_lines=len(all_lines),
                text="\n".join(lines),
            )
        except ValueError, KeyError, TypeError, UnicodeError, AttributeError:
            raise ProbeError(
                "github_invalid", "文件不是可校验的 UTF-8 Git blob，未发送"
            ) from None
