from collections.abc import AsyncIterator
from pathlib import PurePosixPath

from app.model_config.connection import ProbeError
from app.project.github import (
    MAX_BLOB_BYTES,
    MAX_ENTRIES,
    MAX_FILES,
    SECRET,
    SKIP_PARTS,
    GitHub,
)
from app.project.schema import FileEntry, Snapshot

# Formats known to be binary are rejected before requesting their blob. Unknown
# formats still get the UTF-8/control-byte check; this is not a repository allowlist.
BINARY = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".zip",
    ".gz",
    ".tar",
    ".woff",
    ".woff2",
    ".ttf",
    ".mp4",
    ".mp3",
    ".sqlite",
    ".db",
    ".so",
    ".dll",
    ".exe",
    ".pyc",
}


def exclusion(entry: FileEntry) -> str | None:
    path = PurePosixPath(entry.path)
    if any(part in SKIP_PARTS for part in path.parts):
        return "依赖或生成产物，不读取"
    if entry.mode == "120000" or entry.kind == "commit":
        return "符号链接或子模块，不读取目标"
    if (
        SECRET.search(entry.path)
        or path.name == ".env"
        or path.name.startswith(".env.")
    ):
        return "路径疑似涉及秘密，不读取"
    if entry.kind == "blob" and entry.size > MAX_BLOB_BYTES:
        return "文件超过 1 MiB 已验证范围，未读取"
    if path.suffix.lower() in BINARY or path.name in {
        "bun.lock",
        "package-lock.json",
        "yarn.lock",
        "uv.lock",
        "poetry.lock",
    }:
        return "二进制或依赖锁定产物，不读取"
    return None


def priority(entry: FileEntry, focus: str) -> tuple[bool, bool, str]:
    name = PurePosixPath(entry.path).name.lower()
    return (
        not (focus and (entry.path == focus or entry.path.startswith(focus + "/"))),
        name
        not in {
            "readme.md",
            "package.json",
            "pyproject.toml",
            "main.py",
            "app.py",
            "index.ts",
            "index.js",
            "main.go",
            "main.rs",
            "dockerfile",
        },
        entry.path,
    )


async def acquire(client: GitHub, snapshot: Snapshot) -> AsyncIterator[Snapshot]:
    """Yield each safe batch for durable checkpointing before another request."""
    client.requests, client.bytes = snapshot.requests, snapshot.bytes
    entries, fragments = list(snapshot.entries), list(snapshot.fragments)
    excluded = dict(snapshot.excluded)
    directories, files = list(snapshot.directories), list(snapshot.files)
    offsets = dict(snapshot.offsets)
    if not entries and not directories and not snapshot.listing_complete:
        directories = [
            FileEntry(path="", sha=snapshot.repository.tree, kind="tree", mode="040000")
        ]

    def checkpoint() -> Snapshot:
        return Snapshot(
            repository=snapshot.repository,
            entries=list(entries),
            fragments=list(fragments),
            excluded=dict(excluded),
            directories=list(directories),
            files=list(files),
            offsets=dict(offsets),
            requests=client.requests,
            bytes=client.bytes,
            listing_complete=not directories,
        )

    # Breadth first, with one file read after each directory batch. Deep or large
    # trees cannot consume every request before the first verifiable text arrives.
    while directories or files:
        if directories:
            directory = directories[0]
            batch = await client.directory(
                snapshot.repository,
                directory.sha,
                directory.path + "/" if directory.path else "",
            )
            if len(entries) + len(batch) > MAX_ENTRIES:
                raise ProbeError(
                    "github_scope", "目录累计超过已验证范围，已核对成果保留"
                )
            directories.pop(0)
            entries.extend(batch)
            for entry in batch:
                reason = exclusion(entry)
                if reason:
                    excluded[entry.path] = reason
                elif entry.kind == "tree":
                    directories.append(entry)
                else:
                    files.append(entry)
            files.sort(key=lambda entry: priority(entry, snapshot.repository.focus))
            directories.sort(
                key=lambda entry: priority(entry, snapshot.repository.focus)
            )
            yield checkpoint()
        if files and len(fragments) < MAX_FILES:
            entry = files[0]
            focused = entry.path == snapshot.repository.focus
            start = offsets.get(
                entry.path, snapshot.repository.start_line if focused else 1
            )
            end = snapshot.repository.end_line if focused else None
            try:
                fragment = await client.fragment(
                    snapshot.repository, entry, start=start, end=end
                )
            except ProbeError as error:
                if error.code not in {
                    "source_secret",
                    "github_binary",
                    "github_skipped",
                    "github_invalid",
                    "github_range",
                }:
                    raise
                excluded[entry.path] = error.message
            else:
                fragments.append(fragment)
                offsets[entry.path] = fragment.end + 1
                if fragment.end < (end if end is not None else fragment.total_lines):
                    # Rotate partial files rather than let one large file monopolize every batch.
                    files.append(entry)
            files.pop(0)
            yield checkpoint()
        elif not directories:
            return
