import asyncio
import json
import logging
import socket
import ssl
from datetime import UTC, datetime, timedelta

import httpcore
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import Response

from app.model_config import connection, routes
from app.model_config.connection import (
    ProbeError,
    ProbeInput,
    parse_reply,
    public_ip,
    request_once,
)
from tests.test_accounts import client
from tests.test_model_config import FAKE_KEY, account, body, save


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "0.0.0.0",
        "224.0.0.1",
        "100.64.0.1",
        "::1",
        "fc00::1",
        "fe80::1",
        "ff02::1",
        "::ffff:127.0.0.1",
        "::ffff:8.8.8.8",
        "64:ff9b::7f00:1",
        "2002:7f00:1::1",
        "2001:db8::1",
    ],
)
def test_nonpublic_or_tunnel_addresses_are_denied(address):
    assert not public_ip(address)


def test_dns_mixed_answers_and_rebinding_are_checked_before_tcp(monkeypatch):
    async def run():
        loop = asyncio.get_running_loop()
        answers = ["8.8.8.8", "127.0.0.1"]

        async def resolve(*_args, **_kwargs):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in answers
            ]

        monkeypatch.setattr(loop, "getaddrinfo", resolve)
        connected = []

        class Stream:
            def get_extra_info(self, name):
                return ("8.8.8.8", 443)

        async def connect(_self, host, *_args):
            connected.append(host)
            return Stream()

        monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", connect)
        backend = connection.PublicBackend()
        with pytest.raises(ProbeError, match="非公网"):
            await backend.connect_tcp("provider.example.com", 443)
        assert connected == []
        answers[:] = ["8.8.8.8"]
        await backend.connect_tcp("provider.example.com", 443)
        assert connected == ["8.8.8.8"]
        answers[:] = ["10.0.0.1"]
        with pytest.raises(ProbeError):
            await backend.connect_tcp("provider.example.com", 443)
        assert connected == ["8.8.8.8"]

    asyncio.run(run())


def certificate(tmp_path, hostname):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), False)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


@pytest.mark.parametrize(
    "mode",
    [
        "json",
        "sse",
        "list",
        "redirect",
        "wrong_cert",
        "untrusted",
        "peer_mismatch",
        "slow",
        "oversized",
        "ipv6",
        "auth",
        "balance",
        "quota",
        "limited",
        "temporary",
        "invalid",
        "compressed",
        "auth_slow",
        "forbidden_slow",
        "balance_slow",
        "failure_usage",
        "invalid_usage",
        "sse_incomplete_usage",
        "sse_timeout_usage",
        "sse_cut_usage",
        "partial_json_usage",
    ],
)
def test_real_tls_http_boundary(tmp_path, monkeypatch, mode, caplog):
    caplog.set_level(logging.DEBUG)
    cert, key = certificate(
        tmp_path,
        "wrong.example.com" if mode == "wrong_cert" else "provider.example.com",
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    trusted = ssl.create_default_context(cafile=cert)
    untrusted = ssl.create_default_context()
    monkeypatch.setattr(
        connection.ssl,
        "create_default_context",
        lambda: untrusted if mode == "untrusted" else trusted,
    )
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9")
    requests, targets, sni = [], [], []
    context.set_servername_callback(lambda ssl_socket, name, ctx: sni.append(name))
    original_connect = httpcore.AnyIOBackend.connect_tcp
    public = "2606:4700:4700::1111" if mode == "ipv6" else "8.8.8.8"
    local = "::1" if mode == "ipv6" else "127.0.0.1"

    async def run():
        handlers = set()

        async def handler(reader, writer):
            handlers.add(asyncio.current_task())
            try:
                header = await reader.readuntil(b"\r\n\r\n")
                lines = header.decode().split("\r\n")
                headers = dict(
                    line.split(": ", 1) for line in lines[1:] if ": " in line
                )
                payload = await reader.readexactly(
                    int(headers.get("Content-Length", "0"))
                )
                requests.append((lines[0], headers, payload))
                status, mime = 200, "application/json"
                content = json.dumps(
                    {
                        "choices": [{"message": {"content": "OK " + FAKE_KEY}}],
                        "usage": {
                            "prompt_tokens": 4,
                            "completion_tokens": 1,
                            "total_tokens": 5,
                        },
                    }
                ).encode()
                extra = b"X-Untrusted-Echo: " + FAKE_KEY.encode() + b"\r\n"
                if mode == "list":
                    content = b'{"data":[{"id":"actual-model"},{"id":"another"}]}'
                if mode == "sse":
                    mime = "text/event-stream"
                    content = b'data: {"choices":[{"index":0,"delta":{"content":"OK"}}]}\n\ndata: [DONE]\n\n'
                if mode == "redirect":
                    status, extra = (
                        302,
                        b"Location: https://other.example.com/steal\r\n",
                    )
                if mode == "oversized":
                    content = b"x" * (connection.MAX_BYTES + 1)
                if mode in (
                    "auth",
                    "balance",
                    "quota",
                    "limited",
                    "temporary",
                    "invalid",
                ):
                    status = {
                        "auth": 401,
                        "balance": 402,
                        "quota": 429,
                        "limited": 429,
                        "temporary": 503,
                        "invalid": 404,
                    }[mode]
                    content = json.dumps(
                        {
                            "error": {
                                "message": FAKE_KEY,
                                "code": "insufficient_quota"
                                if mode == "quota"
                                else "error",
                            }
                        }
                    ).encode()
                if mode == "compressed":
                    extra = b"Content-Encoding: gzip\r\n"
                if mode in ("auth_slow", "forbidden_slow", "balance_slow"):
                    status = {
                        "auth_slow": 401,
                        "forbidden_slow": 403,
                        "balance_slow": 402,
                    }[mode]
                if mode in ("failure_usage", "invalid_usage", "partial_json_usage"):
                    status = 503 if mode == "failure_usage" else 200
                    content = b'{"usage":{"prompt_tokens":3,"completion_tokens":false,"total_tokens":9},"choices":[]}'
                    if mode == "partial_json_usage":
                        content = content[:-1]
                if mode.startswith("sse_"):
                    mime = "text/event-stream"
                    content = b'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":false,"total_tokens":9}}\n\n'
                length = len(content) + (
                    20 if mode in ("sse_timeout_usage", "sse_cut_usage") else 0
                )
                writer.write(
                    f"HTTP/1.1 {status} Reply\r\nContent-Type: {mime}\r\nContent-Length: {length}\r\nConnection: close\r\n".encode()
                    + extra
                    + b"\r\n"
                )
                if mode in ("slow", "auth_slow", "forbidden_slow", "balance_slow"):
                    await writer.drain()
                    await asyncio.sleep(0.2)
                writer.write(content)
                await writer.drain()
                if mode == "sse_timeout_usage":
                    await asyncio.sleep(0.2)
            except ConnectionError, asyncio.IncompleteReadError:
                pass
            finally:
                writer.close()
                handlers.discard(asyncio.current_task())

        server = await asyncio.start_server(handler, local, 0, ssl=context)
        port = server.sockets[0].getsockname()[1]
        loop = asyncio.get_running_loop()
        original_resolve = loop.getaddrinfo

        async def resolve(host, *args, **kwargs):
            if host == "provider.example.com":
                return [
                    (
                        socket.AF_INET6 if mode == "ipv6" else socket.AF_INET,
                        socket.SOCK_STREAM,
                        6,
                        "",
                        (public, port),
                    )
                ]
            return await original_resolve(host, *args, **kwargs)

        monkeypatch.setattr(loop, "getaddrinfo", resolve)

        # Test-only wire remapping. Production still verifies the exact numeric target;
        # real TCP/TLS/Host/SNI/HTTP/response parsing run against the controlled server.
        async def local_wire(self, host, requested_port, *args):
            assert host == public and requested_port == port
            targets.append((host, requested_port))
            stream = await original_connect(self, local, port, *args)
            original_info = stream.get_extra_info
            stream.get_extra_info = lambda name: (
                (("127.0.0.1" if mode == "peer_mismatch" else public), port)
                if name == "server_addr"
                else original_info(name)
            )
            return stream

        monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", local_wire)
        if mode in (
            "slow",
            "auth_slow",
            "forbidden_slow",
            "balance_slow",
            "sse_timeout_usage",
        ):
            monkeypatch.setattr(connection, "ATTEMPT_SECONDS", 0.05)
        try:
            draft = ProbeInput(
                **body(service_url=f"https://provider.example.com:{port}/v1")
            )
            errors = {
                "redirect": "redirect",
                "wrong_cert": "tls",
                "untrusted": "tls",
                "peer_mismatch": "unsafe_target",
                "slow": "timeout",
                "oversized": "too_large",
                "auth": "authentication",
                "balance": "balance",
                "quota": "balance",
                "limited": "rate_limited",
                "temporary": "temporary_service",
                "invalid": "service_rejected",
                "compressed": "encoding",
                "failure_usage": "temporary_service",
                "invalid_usage": "invalid_response",
                "sse_incomplete_usage": "invalid_response",
                "sse_timeout_usage": "timeout",
                "sse_cut_usage": "transport",
                "partial_json_usage": "invalid_response",
            }
            if mode in ("auth_slow", "forbidden_slow", "balance_slow"):
                monkeypatch.setattr(routes, "recheck_caller", lambda _token: None)
                from sqlmodel import Session

                from app.core.db import engine
                from app.models import User
                owner, _ = account()
                with Session(engine) as session:
                    user = session.get(User, owner)
                result = await routes.probe(
                    "test", draft, "synthetic", user, Response()
                )
                assert not result.ok and result.code == (
                    "balance" if mode == "balance_slow" else "authentication"
                )
                assert (
                    len(result.attempts) == 1
                    and result.attempts[0].total_tokens is None
                )
            elif mode in errors:
                with pytest.raises(ProbeError) as error:
                    await request_once(draft, "test")
                assert error.value.code == errors[mode], repr(error.value.__context__)
                assert error.value.retry == (
                    mode
                    in (
                        "slow",
                        "limited",
                        "temporary",
                        "failure_usage",
                        "sse_timeout_usage",
                    )
                )
                assert FAKE_KEY not in error.value.message
                if mode in (
                    "failure_usage",
                    "invalid_usage",
                    "sse_incomplete_usage",
                    "sse_timeout_usage",
                    "sse_cut_usage",
                ):
                    assert error.value.counts == {
                        "prompt_tokens": 3,
                        "completion_tokens": None,
                        "total_tokens": 9,
                    }
                else:
                    assert error.value.counts == connection.usage(None)
            else:
                models, counts = await request_once(
                    draft, "models" if mode == "list" else "test"
                )
                assert models == (["actual-model", "another"] if mode == "list" else [])
                assert counts["total_tokens"] == (
                    None if mode in ("sse", "list") else 5
                )
        finally:
            server.close()
            await server.wait_closed()
            for task in list(handlers):
                task.cancel()
            await asyncio.gather(*handlers, return_exceptions=True)
        assert len(targets) == 1
        if mode in ("wrong_cert", "untrusted", "peer_mismatch"):
            assert requests == []  # No credential sent before validated TLS/peer.
        else:
            assert len(requests) == 1  # Redirect did not contact a second target.
            line, headers, payload = requests[0]
            assert headers["Host"] == f"provider.example.com:{port}"
            assert headers["Authorization"] == "Bearer " + FAKE_KEY
            assert sni == ["provider.example.com"]
            if mode == "list":
                assert line == "GET /v1/models HTTP/1.1" and not payload
            else:
                assert line == "POST /v1/chat/completions HTTP/1.1"
                assert json.loads(payload) == {
                    "model": "fake-model",
                    "messages": [{"role": "user", "content": "请仅回复 OK"}],
                    "stream": False,
                }
        assert FAKE_KEY not in caplog.text

    asyncio.run(run())


@pytest.mark.parametrize(
    "raw,mime,listing",
    [
        (b"{}", "application/json", False),
        (b'{"choices":[{"message":{"content":" "}}]}', "application/json", False),
        (b'{"data":[{"id":5}]}', "application/json", True),
        (json.dumps({"data": [{"id": FAKE_KEY}]}).encode(), "application/json", True),
        (b"<script>alert(1)</script>", "text/html", True),
        (b"data: {}\n\n", "text/event-stream", False),
        (
            b'data: {"choices":[{"index":0,"delta":{"content":"partial"}}]}\n\n',
            "text/event-stream",
            False,
        ),
    ],
)
def test_malformed_output_does_not_become_success(raw, mime, listing):
    with pytest.raises(ProbeError):
        parse_reply(raw, mime, listing, FAKE_KEY)


def test_api_draft_is_explicit_owned_and_three_attempts_are_bounded(
    monkeypatch, caplog
):
    _, auth = account()
    saved = save(auth).json()
    _, unverified = account(False)
    calls = []

    async def request(draft, kind):
        calls.append(
            (draft.service_url, draft.model_id, draft.api_key.get_secret_value(), kind)
        )
        if len(calls) < 3:
            raise ProbeError("rate_limited", "服务限流", True)
        return ["actual"], connection.usage(None)

    monkeypatch.setattr(routes, "request_once", request)
    monkeypatch.setattr(routes, "BACKOFF_SECONDS", (0, 0))
    url = "/api/v1/model-config/probe/models"
    assert client.post(url, json=body()).status_code == 401
    assert client.post(url, headers=unverified, json=body()).status_code == 403
    for invalid in [
        body(api_key=None),
        body(api_key=""),
        body(service_url=""),
        body(user_id="another"),
        body(disclosure_accepted=False),
    ]:
        result = client.post(url, headers=auth, json=invalid)
        assert result.status_code == 422 and FAKE_KEY not in result.text
    assert calls == []
    result = client.post(
        url,
        headers=auth,
        json=body(
            model_id="",
            service_url="https://draft.example.com/v1",
            api_key="fake-draft-key",
        ),
    )
    assert result.status_code == 200
    assert result.json()["ok"] and len(result.json()["attempts"]) == 3
    assert all(a["total_tokens"] is None for a in result.json()["attempts"])
    assert (
        calls == [("https://draft.example.com/v1", "", "fake-draft-key", "models")] * 3
    )
    assert client.get("/api/v1/model-config", headers=auth).json() == saved
    assert result.headers["cache-control"] == "no-store"
    calls.clear()
    assert (
        client.post(
            url.replace("models", "test"), headers=auth, json=body(model_id="")
        ).status_code
        == 422
    )
    assert calls == []

    async def denied(*_args):
        calls.append(1)
        raise ProbeError("authentication", "认证失败")

    monkeypatch.setattr(routes, "request_once", denied)
    result = client.post(url, headers=auth, json=body())
    assert not result.json()["ok"] and len(calls) == 1
    calls.clear()

    async def temporary(*_args):
        calls.append(1)
        raise ProbeError(
            "timeout", "超时", True, counts=connection.usage({"total_tokens": 9})
        )

    monkeypatch.setattr(routes, "request_once", temporary)
    failed = client.post(url, headers=auth, json=body()).json()["attempts"]
    assert len(failed) == 3
    assert all(a["total_tokens"] == 9 and a["prompt_tokens"] is None for a in failed)
    assert len(calls) == 3
    assert FAKE_KEY not in caplog.text


def test_retry_rechecks_revoked_login(monkeypatch):
    _, auth = account()
    calls = []

    async def revoked_after_first(*_args):
        calls.append(1)
        assert client.post("/api/v1/login/logout", headers=auth).status_code == 200
        raise ProbeError("timeout", "超时", True)

    monkeypatch.setattr(routes, "request_once", revoked_after_first)
    monkeypatch.setattr(routes, "BACKOFF_SECONDS", (0, 0))
    response = client.post("/api/v1/model-config/probe/test", headers=auth, json=body())
    assert response.status_code == 401 and calls == [1]


def test_usage_is_provider_only_and_stream_requires_completion():
    assert connection.usage(
        {"prompt_tokens": True, "completion_tokens": -1, "total_tokens": "5"}
    ) == connection.usage(None)
    models, counts = parse_reply(b'{"data":[]}', "application/json", True, FAKE_KEY)
    assert models == [] and counts == connection.usage(None)
    stream = b'data: {"choices":[{"index":0,"delta":{"content":"OK"}}]}\n\ndata: {"choices":[],"usage":{"total_tokens":7}}\n\ndata: [DONE]\n\n'
    assert (
        parse_reply(stream, "text/event-stream", False, FAKE_KEY)[1]["total_tokens"]
        == 7
    )
