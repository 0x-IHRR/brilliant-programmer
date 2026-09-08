import asyncio
import base64
import hashlib
import json
import socket
import ssl

import httpcore
import pytest

from app.model_config.connection import ProbeError
from app.project.acquisition import acquire
from app.project.analysis import syntax_map
from app.project.github import GitHub, parse_url
from app.project.schema import FileEntry, Fragment, Repository, Snapshot, validate_map
from tests.test_model_connection import certificate

SHA = "a" * 40
TREE = "b" * 40


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/o/r",
        "https://github.com.evil/o/r",
        "https://x@github.com/o/r",
        "https://github.com:443/o/r",
        "https://127.0.0.1/o/r",
        "https://github.com/o/../r",
        "https://github.com/o/r/tree/main/%2e%2e/a",
        "https://github.com/o/r/tree/main/%252e%252e",
        "https://github.com/o/r/tree/main/a%5cb",
        "https://github.com/o/r?access_token=secret",
        "https://github.com/o/r\n",
        "https://github.com/o/r/issues/1",
    ],
)
def test_hostile_urls(url):
    with pytest.raises(ValueError):
        parse_url(url)


def test_refs_come_from_repository_facts(monkeypatch):
    requests = []

    async def get(_self, path, **_kwargs):
        requests.append(path)
        if path == "/repos/o/r":
            return {"private": False, "default_branch": "trunk"}
        if "/matching-refs/heads/" in path:
            return [
                {
                    "ref": "refs/heads/feature/one",
                    "object": {"type": "commit", "sha": SHA},
                }
            ]
        if "/matching-refs/tags/" in path:
            return []
        if "/git/ref/heads/" in path:
            return {"object": {"type": "commit", "sha": SHA}}
        if "/commits/" in path:
            return {"sha": SHA, "commit": {"tree": {"sha": TREE}}}
        if "/trees/" in path:
            return {
                "truncated": False,
                "tree": [
                    {
                        "path": "app.py",
                        "sha": SHA,
                        "mode": "100644",
                        "type": "blob",
                        "size": 1,
                    }
                ],
            }
        raise AssertionError(path)

    monkeypatch.setattr(GitHub, "get", get)
    result = asyncio.run(
        GitHub().resolve("https://github.com/o/r/blob/feature/one/app.py#L1")
    )
    assert (
        result.ref == "feature/one"
        and result.focus == "app.py"
        and result.commit == SHA
    )
    assert "/repos/o/r/commits/" + SHA in requests
    requests.clear()
    assert asyncio.run(GitHub().resolve("https://github.com/o/r.git")).ref == "trunk"
    assert "/repos/o/r/git/ref/heads/trunk" in requests


@pytest.mark.parametrize(
    "text,code",
    [(b"x\0y", "github_binary"), (b"token='ghp_" + b"a" * 36 + b"'", "source_secret")],
)
def test_blob_exclusion_and_identity(monkeypatch, text, code):
    digest = hashlib.sha1(b"blob " + str(len(text)).encode() + b"\0" + text).hexdigest()

    async def get(*_args, **_kwargs):
        return {"encoding": "base64", "content": base64.b64encode(text).decode()}

    monkeypatch.setattr(GitHub, "get", get)
    repo = Repository(owner="o", name="r", ref="main", commit=SHA, tree=TREE)
    entry = FileEntry(path="a", sha=digest, mode="100644", kind="blob", size=len(text))
    with pytest.raises(ProbeError) as caught:
        asyncio.run(GitHub().fragment(repo, entry))
    assert caught.value.code == code
    with pytest.raises(ProbeError) as caught:
        asyncio.run(GitHub().fragment(repo, entry.model_copy(update={"sha": SHA})))
    assert caught.value.code == "github_invalid"


def test_syntax_evidence_and_model_claims_are_separate():
    text = 'import os\nclass Store:\n    __tablename__ = "records"\n    def put(self):\n        self.value = open("data.txt")\nif __name__ == "__main__":\n    Store().put()'
    fragment = Fragment(path="app.py", blob=SHA, start=1, end=7, text=text)
    result = syntax_map([fragment])
    assert {finding.kind for finding in result.confirmed} == {
        "module",
        "entry",
        "call",
        "state",
        "storage",
    }
    raw = json.dumps({"findings": [result.confirmed[-1].model_dump()], "missing": []})
    assert validate_map(raw, [fragment], "").findings
    assert result.unverified == []
    with pytest.raises(ValueError):
        validate_map(raw.replace("Store().put()", "execute_secret()"), [fragment], "")
    with pytest.raises(ValueError):
        validate_map(raw.replace("app.py", "unread.py"), [fragment], "")


def test_batches_resume_without_rereading_or_following_links(monkeypatch):
    from app.project import acquisition

    monkeypatch.setattr(acquisition, "MAX_FILES", 2)
    requests = []

    async def directory(_self, _repo, _tree, prefix=""):
        requests.append("tree:" + prefix)
        return [
            FileEntry(path="main.py", sha=SHA, kind="blob", mode="100644", size=10),
            FileEntry(path="other.py", sha=SHA, kind="blob", mode="100644", size=10),
            FileEntry(path="last.py", sha=SHA, kind="blob", mode="100644", size=10),
            FileEntry(path="node_modules", sha=SHA, kind="tree", mode="040000"),
            FileEntry(path="external", sha=SHA, kind="blob", mode="120000", size=8),
            FileEntry(
                path="large.py",
                sha=SHA,
                kind="blob",
                mode="100644",
                size=1024 * 1024 + 1,
            ),
        ]

    async def fragment(_self, _repo, entry):
        requests.append(entry.path)
        return Fragment(path=entry.path, blob=SHA, start=1, end=1, text="print(1)")

    monkeypatch.setattr(GitHub, "directory", directory)
    monkeypatch.setattr(GitHub, "fragment", fragment)

    async def run():
        snapshot = Snapshot(
            repository=Repository(
                owner="o", name="r", commit=SHA, tree=TREE, ref="main"
            )
        )
        async for current in acquire(GitHub(), snapshot):
            snapshot = current
            if snapshot.fragments:
                break
        assert len(snapshot.fragments) == 1
        saved = Snapshot.model_validate_json(snapshot.model_dump_json())
        async for current in acquire(GitHub(), saved):
            snapshot = current
        assert len(snapshot.fragments) == 2 and len(snapshot.files) == 1
        assert set(snapshot.excluded) == {"node_modules", "external", "large.py"}

    asyncio.run(run())
    assert requests == ["tree:", "main.py", "last.py"]


def test_fragment_range_and_resource_ceiling(monkeypatch):
    from app.project.github import MAX_FRAGMENT_BYTES

    text = b"# safe line\n" * 87000
    digest = hashlib.sha1(b"blob " + str(len(text)).encode() + b"\0" + text).hexdigest()

    async def get(*_args, **_kwargs):
        return {"encoding": "base64", "content": base64.b64encode(text).decode()}

    monkeypatch.setattr(GitHub, "get", get)
    entry = FileEntry(
        path="large.py", sha=digest, kind="blob", mode="100644", size=len(text)
    )
    repo = Repository(owner="o", name="r", commit=SHA, tree=TREE, ref="main")
    fragment = asyncio.run(GitHub().fragment(repo, entry))
    assert len(fragment.text.encode()) <= MAX_FRAGMENT_BYTES and fragment.end == len(
        fragment.text.splitlines()
    )
    assert fragment.end < 87000


def test_ambiguous_refs_do_not_guess(monkeypatch):
    async def get(_self, path, **_kwargs):
        if path == "/repos/o/r":
            return {"private": False, "default_branch": "main"}
        namespace = "heads" if "/heads/" in path else "tags"
        return [
            {
                "ref": f"refs/{namespace}/release",
                "object": {"type": "commit", "sha": SHA},
            }
        ]

    monkeypatch.setattr(GitHub, "get", get)
    with pytest.raises(ProbeError) as caught:
        asyncio.run(GitHub().resolve("https://github.com/o/r/tree/release"))
    assert caught.value.code == "github_ambiguous_ref"


def test_directory_and_request_resource_limits(monkeypatch):
    from app.project.github import MAX_ENTRIES, MAX_REQUESTS

    client = GitHub()
    client.requests = MAX_REQUESTS
    with pytest.raises(ProbeError) as caught:
        asyncio.run(client.get("/repos/o/r"))
    assert caught.value.code == "github_scope"

    async def get(*_args, **_kwargs):
        return {"tree": [{}] * (MAX_ENTRIES + 1), "truncated": False}

    monkeypatch.setattr(GitHub, "get", get)
    repo = Repository(owner="o", name="r", commit=SHA, tree=TREE, ref="main")
    with pytest.raises(ProbeError) as caught:
        asyncio.run(GitHub().directory(repo, TREE))
    assert caught.value.code == "github_scope"


def test_malicious_source_is_only_parsed(tmp_path):
    marker = tmp_path / "must-not-exist"
    text = f"__import__('pathlib').Path({str(marker)!r}).write_text('owned')"
    result = syntax_map(
        [Fragment(path="setup.py", blob=SHA, start=1, end=1, text=text)]
    )
    assert result.confirmed and not marker.exists()


@pytest.mark.parametrize(
    "status,extra,expected",
    [
        (200, b"", None),
        (404, b"", "github_unavailable"),
        (403, b"X-RateLimit-Remaining: 0\r\n", "github_rate_limited"),
        (302, b"Location: https://evil.example/\r\n", "github_unavailable"),
        (200, b"Content-Encoding: gzip\r\n", "github_encoding"),
        (200, b"", "github_scope"),
    ],
)
def test_actual_github_tls_request(tmp_path, monkeypatch, status, extra, expected):
    cert, key = certificate(tmp_path, "api.github.com")
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert, key)
    trusted = ssl.create_default_context(cafile=cert)
    monkeypatch.setattr(ssl, "create_default_context", lambda: trusted)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    original_connect = httpcore.AnyIOBackend.connect_tcp
    requests = []

    async def run():
        async def handler(reader, writer):
            request = await reader.readuntil(b"\r\n\r\n")
            requests.append(request)
            body = (
                b"x" * (2 * 1024 * 1024 + 1)
                if expected == "github_scope"
                else b'{"private":false}'
            )
            writer.write(
                f"HTTP/1.1 {status} Result\r\nContent-Length: {len(body)}\r\n".encode()
                + extra
                + b"Connection: close\r\n\r\n"
                + body
            )
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(handler, "127.0.0.1", 0, ssl=server_context)
        port = server.sockets[0].getsockname()[1]

        async def resolve(*_args, **_kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]

        async def connect(self, host, _port, *args):
            assert host == "8.8.8.8"
            stream = await original_connect(self, "127.0.0.1", port, *args)
            original_info = stream.get_extra_info
            stream.get_extra_info = lambda name: (
                ("8.8.8.8", 443) if name == "server_addr" else original_info(name)
            )
            return stream

        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
        monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", connect)
        try:
            if expected:
                with pytest.raises(ProbeError) as caught:
                    await GitHub().get("/repos/o/r")
                assert caught.value.code == expected
            else:
                assert await GitHub().get("/repos/o/r") == {"private": False}
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(run())
    assert len(requests) == 1 and b"Host: api.github.com" in requests[0]
    assert b"Authorization" not in requests[0] and requests[0].startswith(
        b"GET /repos/o/r "
    )
