"""Isolated 0018 data upgrade: no retroactive Boss or level/award changes."""

import os
import subprocess
import sys
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.db import engine

schema = "issue26_migration_" + uuid.uuid4().hex[:8]
with engine.begin() as connection:
    connection.execute(text(f'CREATE SCHEMA "{schema}"'))
url = make_url(str(settings.DATABASE_URL)).update_query_dict(
    {"options": "-csearch_path=" + schema}
)
isolated = create_engine(url, hide_parameters=True)
env = {**os.environ, "DATABASE_URL": url.render_as_string(hide_password=False)}


def migrate(revision):
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        env=env,
        capture_output=True,
    )
    assert result.returncode == 0, "isolated migration failed; credentials omitted"


migrate("0018_random_recommendations")
tables = [
    "user",
    "training_run",
    "training_submission",
    "practice_award",
    "training_draft",
    "draft_collection",
]
with isolated.begin() as connection:
    owner = connection.execute(
        text(
            "SELECT user_id FROM public.training_run WHERE formal_submitted_at IS NOT NULL AND id IN (SELECT run_id FROM public.draft_collection WHERE help_id IS NULL) LIMIT 1"
        )
    ).scalar_one()
    for table, where in zip(
        tables,
        [
            "id=:owner",
            "user_id=:owner",
            "run_id IN (SELECT id FROM training_run)",
            "run_id IN (SELECT id FROM training_run)",
            "run_id IN (SELECT id FROM training_run)",
            "run_id IN (SELECT id FROM training_run) AND help_id IS NULL",
        ],
        strict=True,
    ):
        names = (
            connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema=:schema AND table_name=:table ORDER BY ordinal_position"
                ),
                {"schema": schema, "table": table},
            )
            .scalars()
            .all()
        )
        columns = ",".join(f'"{name}"' for name in names)
        connection.execute(
            text(
                f'INSERT INTO "{table}" ({columns}) SELECT {columns} FROM public."{table}" WHERE {where}'
            ),
            {"owner": owner},
        )
    before = {
        table: connection.execute(
            text(
                f'SELECT to_jsonb(t)::text FROM "{table}" t ORDER BY to_jsonb(t)::text'
            )
        )
        .scalars()
        .all()
        for table in tables
    }
migrate("0019_first_boss")
with isolated.connect() as connection:
    for table in tables:
        after = (
            connection.execute(
                text(
                    f'SELECT to_jsonb(t)::text FROM "{table}" t ORDER BY to_jsonb(t)::text'
                )
            )
            .scalars()
            .all()
        )
        assert after == before[table], table
    for table in ["boss_attempt", "boss_promotion"]:
        assert (
            connection.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one()
            == 0
        )
print(  # noqa: T201 -- synthetic schema recovery coordinates
    schema,
    {table: len(rows) for table, rows in before.items()},
    "unchanged; no invented Boss or promotion",
)
isolated.dispose()
