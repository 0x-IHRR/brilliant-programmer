"""Container entry points; all application processes retain the production gates."""

import argparse
import asyncio
import ssl
import time
import urllib.request

from sqlalchemy import text

from app.operations import maintenance, state


async def worker() -> None:
    from app.training.worker import main

    state.require_open()
    async with asyncio.TaskGroup() as tasks:
        tasks.create_task(maintenance.loop())
        tasks.create_task(main())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=[
            "api",
            "worker",
            "health-api",
            "health-worker",
            "check",
            "maintenance",
        ],
    )
    command = parser.parse_args().command
    state.require_open()
    if command == "health-api":
        context = ssl.create_default_context(cafile="/tls/cert.pem")
        with urllib.request.urlopen(
            "https://localhost:8443/health", context=context, timeout=2
        ) as response:
            if response.status != 200:
                raise RuntimeError("应用未健康")
        return
    if command == "health-worker":
        from app.core.db import engine

        directory = state.root()
        assert directory
        if time.time() - (directory / "maintenance.heartbeat").stat().st_mtime > 180:
            raise RuntimeError("留存维护未运行")
        with engine.connect() as connection:
            alive = connection.execute(
                text(
                    "SELECT EXISTS(SELECT 1 FROM procrastinate_workers WHERE last_heartbeat > now() - interval '30 seconds')"
                )
            ).scalar_one()
        if not alive:
            raise RuntimeError("后台队列未健康")
        return
    maintenance.logging_setup()
    if command == "api":
        import uvicorn

        uvicorn.run(
            "app.main:app",
            host="0.0.0.0",
            port=8443,
            ssl_keyfile="/tls/key.pem",
            ssl_certfile="/tls/cert.pem",
            proxy_headers=False,
            access_log=False,
            log_config=None,
        )
    elif command == "worker":
        asyncio.run(worker())
    elif command == "maintenance":
        maintenance.run()
    else:
        from app.account_erasure.operations import replay

        replay()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Never emit exception values, SQL, credentials or restored source text.
        raise SystemExit("托管操作失败；请核对独立恢复状态、健康与脱敏日志") from None
