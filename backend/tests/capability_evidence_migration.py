"""Isolated 0015 -> 0016 witness using synthetic records already in this test DB."""

import os
import subprocess
import sys
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.db import engine
from app.main import app  # noqa: F401 -- register existing model metadata

schema = "issue17_migration_" + uuid.uuid4().hex[:8]
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


migrate("0015_independent")
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
    "draft_collection",
    "help_delivery",
    "independent_work",
    "independent_observation",
    "help_confirmation",
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
migrate("0016_capability_evidence")
with isolated.connect() as connection:
    for table in tables:
        expression = "to_jsonb(t)"
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
    expected = connection.execute(
        text("""SELECT s.id::text, r.user_id::text,
        row_number() OVER (PARTITION BY r.user_id ORDER BY s.created_at,s.id),
        s.created_at, 'legacy_created_at_uuid' FROM training_submission s
        JOIN training_run r ON r.id=s.run_id WHERE s.kind='original' AND s.practice_help_id IS NULL
        ORDER BY r.user_id,s.created_at,s.id""")
    ).all()
    actual = connection.execute(
        text(
            "SELECT original_id::text,user_id::text,position,submitted_at,source FROM capability_original_order ORDER BY user_id,position"
        )
    ).all()
    assert expected and actual == expected
print(  # noqa: T201 -- synthetic evidence metadata, never credentials
    schema,
    {table: len(rows) for table, rows in before.items()},
    "preserved; legacy originals ordered",
    len(actual),
)  # noqa: T201
isolated.dispose()
