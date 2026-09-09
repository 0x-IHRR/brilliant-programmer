"""Isolated 0022 -> 0023: real frozen corrected promotions, no model/network."""

import os
import subprocess
import sys
import uuid

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.db import engine

schema = "issue28_migration_" + uuid.uuid4().hex[:8]
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


migrate("upgrade", "0022_score_review")
# Copy only this dedicated test database's synthetic app facts in actual FK order.
# The target's old columns deliberately omit the new revalidation fields.
before = {}
with isolated.begin() as connection:
    unknown = connection.execute(
        text("""
        SELECT p.id,p.original_id FROM public.boss_promotion p
        JOIN public.score_review r ON r.run_id=p.run_id
        WHERE r.status='completed' AND r.decision='corrected'
        ORDER BY p.id LIMIT 1
    """)
    ).one()
    inspector = inspect(connection)
    for table, _ in inspector.get_sorted_table_and_fkc_names(schema=schema):
        if (
            table is None
            or table == "alembic_version"
            or table.startswith("procrastinate_")
        ):
            continue
        columns = [c["name"] for c in inspector.get_columns(table, schema=schema)]
        names = ",".join(f'"{column}"' for column in columns)
        where = (
            " WHERE original_id != :unknown_original"
            if table == "capability_original_order"
            else ""
        )
        connection.execute(
            text(
                f'INSERT INTO "{table}" ({names}) SELECT {names} FROM public."{table}"{where}'
            ),
            {"unknown_original": unknown.original_id},
        )
        before[table] = (
            names,
            connection.execute(
                text(
                    f'SELECT jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text) FROM (SELECT {names} FROM "{table}") t'
                )
            ).scalar(),
        )
    expected = (
        connection.execute(
            text("""
        SELECT p.id FROM boss_promotion p JOIN score_review r ON r.run_id=p.run_id
        WHERE r.status='completed' AND r.decision='corrected'
    """)
        )
        .scalars()
        .all()
    )
    expected = [pid for pid in expected if pid != unknown.id]
    assert expected, "run the real revalidation tests first"
migrate("upgrade", "head")
with isolated.begin() as connection:
    for table, (names, original) in before.items():
        assert (
            connection.execute(
                text(
                    f'SELECT jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text) FROM (SELECT {names} FROM "{table}") t'
                )
            ).scalar()
            == original
        ), table
    actual = connection.execute(
        text("SELECT promotion_id,kind,sequence FROM boss_revalidation")
    ).all()
    assert {(row[0], row[1], row[2]) for row in actual} == {
        (pid, "required", 1) for pid in expected
    }
    assert (
        connection.execute(text("SELECT count(*) FROM boss_disposition")).scalar() == 0
    )
migrate("upgrade", "head")
with isolated.begin() as connection:
    assert connection.execute(
        text("SELECT count(*) FROM boss_revalidation")
    ).scalar() == len(expected)
migrate("downgrade", "0022_score_review", success=False)
for query in (
    "UPDATE boss_revalidation SET kind='resolved'",
    "DELETE FROM boss_revalidation",
):
    try:
        with isolated.begin() as connection:
            connection.execute(text(query))
        raise AssertionError("append-only revalidation changed")
    except Exception as error:
        assert "boss facts are immutable" in str(error)
print(  # noqa: T201 -- named retained verification resource, no credentials
    f"0022 frozen promotion/review facts preserved; {len(expected)} proven corrections linked once; missing original-order remains unknown; immutable events protect downgrade; schema={schema}"
)
