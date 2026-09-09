"""Isolated 0020->0021 round-trip preserves real first-Boss legacy facts."""

import os
import subprocess
import sys
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.db import engine

schema = "issue27_migration_" + uuid.uuid4().hex[:8]
with engine.begin() as connection:
    connection.execute(text(f'CREATE SCHEMA "{schema}"'))
url = make_url(str(settings.DATABASE_URL)).update_query_dict(
    {"options": "-csearch_path=" + schema}
)
isolated = create_engine(url, hide_parameters=True)
env = {**os.environ, "DATABASE_URL": url.render_as_string(hide_password=False)}


def migrate(command, target, success=True):
    result = subprocess.run(
        [sys.executable, "-m", "alembic", command, target], env=env, capture_output=True
    )
    assert (result.returncode == 0) == success, (
        "isolated migration outcome unexpected; credentials omitted"
    )


migrate("upgrade", "0020_free_topic")
with isolated.begin() as connection:
    run, owner = connection.execute(
        text(
            "SELECT run_id,user_id FROM public.boss_promotion WHERE stage_version='first-boss-v1' LIMIT 1"
        )
    ).one()
    before = {}
    for table, where in [
        ("user", "id=:owner"),
        ("training_run", "id=:run"),
        ("training_submission", "run_id=:run"),
        ("practice_award", "run_id=:run"),
        ("boss_attempt", "run_id=:run"),
        ("boss_promotion", "run_id=:run"),
        ("independent_work", "run_id=:run"),
    ]:
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
        names = ",".join(f'"{column}"' for column in columns)
        connection.execute(
            text(
                f'INSERT INTO "{table}" ({names}) SELECT {names} FROM public."{table}" WHERE {where}'
            ),
            {"owner": owner, "run": run},
        )
        before[table] = (
            connection.execute(text(f'SELECT row_to_json(t) FROM "{table}" t'))
            .scalars()
            .all()
        )
migrate("upgrade", "head")
with isolated.begin() as connection:
    for table, expected in before.items():
        values = (
            connection.execute(text(f'SELECT row_to_json(t) FROM "{table}" t'))
            .scalars()
            .all()
        )
        if table == "independent_work":
            assert all(
                row.pop("history_snapshot") is None
                and row.pop("comparison_plan") is None
                and row.pop("comparison_results") == []
                for row in values
            )
        assert values == expected, table
    connection.execute(
        text(
            "UPDATE independent_work SET history_snapshot='null'::json,comparison_plan='null'::json"
        )
    )
migrate("downgrade", "0020_free_topic")
migrate("upgrade", "head")
with isolated.begin() as connection:
    connection.execute(text("UPDATE independent_work SET history_snapshot='{}'::json"))
migrate("downgrade", "0020_free_topic", success=False)
for table in ["boss_attempt", "boss_promotion"]:
    try:
        with isolated.begin() as connection:
            connection.execute(text(f'DELETE FROM "{table}"'))
        raise AssertionError("immutable boss fact deleted")
    except Exception as error:
        assert "boss facts are immutable" in str(error)
print(  # noqa: T201 -- named retained verification resource
    f"Legacy first-Boss originals/awards/promotion/private comparison preserved; new facts block downgrade; schema={schema}"
)
