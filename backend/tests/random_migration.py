"""Old first-round data stays exact; only explicit new recommendation facts count."""

import os
import subprocess
import sys
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from app.core.config import settings
from app.core.db import engine

schema = "issue19_migration_" + uuid.uuid4().hex[:8]
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


migrate("0017_prerequisite_unlocks")
with isolated.begin() as connection:
    # Copy a real synthetic owner's successful and failed/first runs without any
    # new column. Mark selection with the old shape before immutable trigger exists.
    owner = connection.execute(
        text(
            "SELECT user_id FROM public.training_run WHERE formal_submitted_at IS NOT NULL LIMIT 1"
        )
    ).scalar_one()
    for table, where in [
        ("user", "id=:owner"),
        ("training_run", "user_id=:owner"),
        ("training_submission", "run_id IN (SELECT id FROM training_run)"),
        ("practice_award", "run_id IN (SELECT id FROM training_run)"),
        ("training_draft", "run_id IN (SELECT id FROM training_run)"),
    ]:
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
    connection.execute(
        text(
            "UPDATE training_run SET selection=json_build_object('seed','legacy','candidates',json_build_array(target),'goal','legacy first')"
        )
    )
    tables = [
        "user",
        "training_run",
        "training_submission",
        "practice_award",
        "training_draft",
    ]
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
migrate("head")
with isolated.connect() as connection:
    for table in tables:
        value = (
            "to_jsonb(t)-'recommendation_delivered_at'"
            if table == "training_run"
            else "to_jsonb(t)"
        )
        after = (
            connection.execute(
                text(
                    f'SELECT ({value})::text FROM "{table}" t ORDER BY ({value})::text'
                )
            )
            .scalars()
            .all()
        )
        assert after == before[table], table
    assert (
        connection.execute(
            text(
                "SELECT count(*) FROM training_run WHERE recommendation_delivered_at IS NOT NULL"
            )
        ).scalar_one()
        == 0
    )
    assert (
        connection.execute(text("SELECT count(*) FROM random_preference")).scalar_one()
        == 0
    )
# Legacy first cannot be counted merely because it has a public candidate.
try:
    with isolated.begin() as connection:
        connection.execute(
            text(
                "UPDATE training_run SET recommendation_delivered_at=now() WHERE candidate IS NOT NULL"
            )
        )
except DBAPIError:
    pass
else:
    raise AssertionError("legacy publication improperly counted")
print(  # noqa: T201 -- synthetic schema recovery location only
    schema,
    "old user/runs/answers/awards/drafts unchanged; no invented recommendation count",
)  # noqa: T201
isolated.dispose()
