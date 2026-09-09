"""Isolated fresh and 0014 -> 0015 upgrade, retaining the synthetic witness schema."""

import os
import subprocess
import sys
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.db import engine

schema = "issue16_migration_" + uuid.uuid4().hex[:8]
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


migrate("0014_draft_conflicts")
before = {}
with isolated.begin() as connection:
    identity = connection.execute(
        text(
            "SELECT id FROM public.training_run WHERE launch_mode='practice' AND candidate IS NOT NULL LIMIT 1"
        )
    ).scalar_one()
    for table in ("user", "training_run"):
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
        where = (
            "id=:id"
            if table == "training_run"
            else "id=(SELECT user_id FROM public.training_run WHERE id=:id)"
        )
        connection.execute(
            text(
                f'INSERT INTO "{table}" ({columns}) SELECT {columns} FROM public."{table}" WHERE {where}'
            ),
            {"id": identity},
        )
    before = dict(
        connection.execute(text("SELECT * FROM training_run")).mappings().one()
    )
migrate("head")
with isolated.connect() as connection:
    after = dict(
        connection.execute(text("SELECT * FROM training_run")).mappings().one()
    )
    assert {key: after[key] for key in before} == before
    assert (
        after["launch_mode"] == "practice"
        and after["origin_id"] is None
        and after["converted_sequence"] is None
    )
    assert (
        connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        == "0015_independent"
    )
try:
    with isolated.begin() as connection:
        connection.execute(text("UPDATE training_run SET launch_mode='independent'"))
except Exception as error:
    assert "round mode identity is immutable" in str(error)
else:
    raise AssertionError("old practice round was promoted in place")
sys.stdout.write(
    f"Preserved legacy round; fresh 0001→0014→0015 and mode trigger passed. Schema: {schema}\n"
)
