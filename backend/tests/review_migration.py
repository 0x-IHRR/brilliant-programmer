"""Isolated 0021 -> 0022 round-trip: original/evaluation/order/points stay intact."""

import os
import subprocess
import sys
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.db import engine

schema = "issue25_migration_" + uuid.uuid4().hex[:8]
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


migrate("upgrade", "0021_boss_stages")
with isolated.begin() as connection:
    run, owner = connection.execute(
        text(
            "SELECT a.run_id,a.user_id FROM public.review_award a JOIN public.training_run r ON r.id=a.run_id WHERE r.origin_id IS NULL LIMIT 1"
        )
    ).one()
    before = {}
    for table, where in [
        ("user", "id=:owner"),
        ("training_run", "id=:run"),
        ("training_submission", "run_id=:run"),
        ("training_evaluation", "run_id=:run"),
        ("capability_original_order", "user_id=:owner"),
        ("practice_award", "run_id=:run"),
    ]:
        connection.execute(
            text(f'INSERT INTO "{table}" SELECT * FROM public."{table}" WHERE {where}'),
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
        assert (
            connection.execute(text(f'SELECT row_to_json(t) FROM "{table}" t'))
            .scalars()
            .all()
            == expected
        ), table
    assert connection.execute(text("SELECT count(*) FROM score_review")).scalar() == 0
migrate("downgrade", "0021_boss_stages")
migrate("upgrade", "head")
with isolated.begin() as connection:
    for table in ("score_review", "review_award"):
        connection.execute(
            text(
                f'INSERT INTO "{table}" SELECT * FROM public."{table}" WHERE run_id=:run'
            ),
            {"run": run},
        )
migrate("downgrade", "0021_boss_stages", success=False)
for query in (
    "UPDATE score_review SET snapshot='{}'::json",
    "UPDATE score_review SET decision='pending'",
    "DELETE FROM review_award",
):
    try:
        with isolated.begin() as connection:
            connection.execute(text(query))
        raise AssertionError("accepted review facts changed")
    except Exception as error:
        assert "immutable" in str(error)
print(  # noqa: T201 -- retained verification resource
    f"0021 originals/order/evaluation/points preserved; immutable review protects downgrade; schema={schema}"
)
