"""Create ignored local secrets and TLS material without printing them."""

import argparse
import base64
import json
import os
import secrets
import socket
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRIVATE = ROOT / ".private"
PORTS = (16392, 11505, 18405, 18138, 18443)


def ports_available() -> None:
    busy = []
    for port in PORTS:
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                busy.append(port)
    if busy:
        raise RuntimeError("本产品端口已占用：" + ", ".join(map(str, busy)))


def exclusive(path: Path, content: str, mode: int = 0o600) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(descriptor, "w") as output:
        output.write(content)


def prepare() -> None:
    if os.getuid() == 0 or os.getgid() == 0:
        raise RuntimeError("拒绝将容器配置为 root；请用普通主机用户准备环境")
    ports_available()
    PRIVATE.mkdir(mode=0o700, exist_ok=True)
    state = PRIVATE / "state"
    tls = PRIVATE / "tls"
    for directory in (state, tls, state / "logs", state / "unreferenced-cache"):
        directory.mkdir(mode=0o700, exist_ok=True)
    key = base64.b64encode(secrets.token_bytes(32)).decode()
    values = {
        "APP_GID": str(os.getgid()),
        "APP_UID": str(os.getuid()),
        "API_PORT": "18138",
        "APP_DATABASE": "bp",
        "DB_PORT": "16392",
        "FIRST_SUPERUSER": "admin@example.com",
        "FIRST_SUPERUSER_PASSWORD": secrets.token_urlsafe(24),
        "FRONTEND_HOST": "https://localhost:18443",
        "HTTPS_PORT": "18443",
        "MAILPIT_HTTP_PORT": "18405",
        "MODEL_ACTIVE_KEY_VERSION": "v1",
        "MODEL_ENCRYPTION_KEYS": json.dumps({"v1": key}, separators=(",", ":")),
        "POSTGRES_PASSWORD": secrets.token_urlsafe(32),
        "SECRET_KEY": secrets.token_urlsafe(48),
        "SMTP_PORT": "11505",
    }
    exclusive(
        PRIVATE / "runtime.env",
        "".join(f"{name}={value}\n" for name, value in values.items()),
    )
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "30",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost,IP:127.0.0.1",
            "-keyout",
            str(tls / "key.pem"),
            "-out",
            str(tls / "cert.pem"),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    (tls / "key.pem").chmod(0o600)
    (tls / "cert.pem").chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["ports", "prepare"])
    command = parser.parse_args().command
    if command == "ports":
        ports_available()
    else:
        prepare()


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from None
