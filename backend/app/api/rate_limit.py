import hashlib
import hmac
from datetime import UTC, datetime

from fastapi import HTTPException, Request
from sqlalchemy import text

from app.core.config import settings
from app.core.db import engine


def protect_auth(request: Request) -> None:
    # One PostgreSQL counter per client/path/minute also covers multiple API processes.
    # Forwarded headers are deliberately not trusted by this local application.
    host = request.client.host if request.client else "unknown"
    key = hmac.new(
        settings.SECRET_KEY.encode(),
        f"{host}:{request.url.path}".encode(),
        hashlib.sha256,
    ).hexdigest()
    minute = int(datetime.now(UTC).timestamp()) // 60
    with engine.begin() as connection:
        count = connection.execute(
            text("""
            INSERT INTO auth_rate (key, minute, count) VALUES (:key, :minute, 1)
            ON CONFLICT (key) DO UPDATE SET
              count = CASE WHEN auth_rate.minute = EXCLUDED.minute THEN auth_rate.count + 1 ELSE 1 END,
              minute = EXCLUDED.minute
            RETURNING count
        """),
            {"key": key, "minute": minute},
        ).scalar_one()
        connection.execute(
            text("DELETE FROM auth_rate WHERE minute < :old"), {"old": minute - 5}
        )
    if count > 60:
        raise HTTPException(
            429, "请求过于频繁，请一分钟后重试", headers={"Retry-After": "60"}
        )
