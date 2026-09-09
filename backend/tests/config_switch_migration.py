"""Isolated 0012 -> 0013 witness using synthetic records already in this test DB."""

import os
import subprocess
import sys
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.db import engine

schema = "issue15_migration_" + uuid.uuid4().hex[:8]
with engine.begin() as connection:
    connection.execute(text(f'CREATE SCHEMA "{schema}"'))
url = make_url(str(settings.DATABASE_URL)).update_query_dict(
    {"options": "-csearch_path=" + schema}
)
env = {**os.environ, "DATABASE_URL": url.render_as_string(hide_password=False)}


def migrate(revision):
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        env=env,
        capture_output=True,
    )
    assert result.returncode == 0, "isolated migration failed (credentials omitted)"


migrate("0012_guided")
isolated = create_engine(url)
tables = [
    "user",
    "model_config",
    "training_run",
    "concept_help",
    "training_submission",
    "practice_award",
    "training_attempt",
    "concept_attempt",
    "submission_attempt",
    "training_evaluation",
    "evaluation_attempt",
    "project_run",
    "project_attempt",
    "training_draft",
    "practice_draft",
]
before = {}
with isolated.begin() as connection:
    for table in tables:
        columns = (
            connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema=:schema AND table_name=:table ORDER BY ordinal_position"
                ),
                {"schema": schema, "table": table},
            )
            .scalars()
            .all()
        )
        names = ",".join('"' + name + '"' for name in columns)
        connection.execute(
            text(
                f'INSERT INTO "{table}" ({names}) SELECT {names} FROM public."{table}"'
            )
        )
        before[table] = (
            connection.execute(
                text(
                    f'SELECT to_jsonb(t)::text FROM "{table}" t ORDER BY to_jsonb(t)::text'
                )
            )
            .scalars()
            .all()
        )
    assert before["model_config"] and before["training_run"]
migrate("0013_config_revocation")
with isolated.connect() as connection:
    for table in tables:
        expression = (
            "(to_jsonb(t)-'revoked')" if table == "model_config" else "to_jsonb(t)"
        )
        after = (
            connection.execute(
                text(
                    f'SELECT {expression}::text FROM "{table}" t ORDER BY {expression}::text'
                )
            )
            .scalars()
            .all()
        )
        assert after == before[table], table
    assert (
        connection.execute(
            text("SELECT count(*) FROM model_config WHERE revoked")
        ).scalar()
        == 0
    )
    assert connection.execute(text("SELECT count(*) FROM probe_attempt")).scalar() == 0
print(  # noqa: T201 -- synthetic migration recovery location/counts, never credentials
    schema,
    {table: len(rows) for table, rows in before.items()},
    "preserved; old configs revoked=false",
)
isolated.dispose()
