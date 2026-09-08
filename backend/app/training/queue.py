"""One PostgreSQL queue; only persisted training IDs cross the task boundary."""

import procrastinate

from app.core.config import settings

DSN = str(settings.DATABASE_URL).replace("postgresql+psycopg://", "postgresql://", 1)
queue = procrastinate.App(
    connector=procrastinate.PsycopgConnector(conninfo=DSN),
    worker_defaults={"concurrency": 1, "abort_job_polling_interval": 0.2},
)
