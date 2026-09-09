"""Real 0026→0027 upgrade pins active routes without changing original facts."""

import os
import subprocess
import sys
import uuid

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from app.core.config import settings
from app.core.db import engine

schema = "issue24_migration_" + uuid.uuid4().hex[:8]
with engine.begin() as connection:
    connection.execute(text(f'CREATE SCHEMA "{schema}"'))
url = make_url(str(settings.DATABASE_URL)).update_query_dict(
    {"options": "-csearch_path=" + schema}
)
isolated = create_engine(url, hide_parameters=True)
env = {**os.environ, "DATABASE_URL": url.render_as_string(hide_password=False)}


def migrate(target):
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", target],
        env=env,
        capture_output=True,
    )
    assert result.returncode == 0, "isolated migration failed; credentials omitted"


migrate("0026_project_training")
with isolated.begin() as connection:
    run, owner, topic, project = connection.execute(
        text("""
        SELECT r.id,r.user_id,p.topic_id,p.project_run_id
        FROM public.training_run r
        JOIN public.project_topic p ON p.topic_id::text=r.selection->>'topic_id'
        WHERE r.formal_submitted_at IS NOT NULL
        ORDER BY r.created_at DESC LIMIT 1
    """)
    ).one()
    params = {"run": run, "owner": owner, "topic": topic, "project": project}
    scopes = [
        ("user", "id=:owner"),
        ("project_run", "id=:project"),
        ("topic", "id=:topic"),
        ("topic_version", "topic_id=:topic"),
        ("topic_job", "topic_id=:topic"),
        ("project_topic", "topic_id=:topic"),
        ("project_training_input", "topic_id=:topic"),
        ("project_training_version", "version_id IN (SELECT id FROM topic_version)"),
        ("training_run", "id=:run"),
        ("project_training_materials", "run_id=:run"),
        ("training_submission", "run_id=:run"),
        ("practice_award", "run_id=:run"),
    ]
    before, columns = {}, {}
    for table, where in scopes:
        names = [
            column["name"]
            for column in inspect(connection).get_columns(table, schema=schema)
        ]
        columns[table] = ",".join(f'"{name}"' for name in names)
        connection.execute(
            text(
                f'INSERT INTO "{table}" ({columns[table]}) SELECT {columns[table]} FROM public."{table}" WHERE {where}'
            ),
            params,
        )
        before[table] = connection.execute(
            text(
                f'SELECT {columns[table]} FROM "{table}" ORDER BY id'
                if "id" in names
                else f'SELECT {columns[table]} FROM "{table}" ORDER BY 1'
            )
        ).all()
    active = connection.execute(
        text("SELECT active_id FROM topic WHERE id=:topic"), params
    ).scalar_one()
    assert active is not None
migrate("head")
migrate("head")
with isolated.begin() as connection:
    for table, _ in scopes:
        names = [
            column["name"]
            for column in inspect(connection).get_columns(table, schema=schema)
        ]
        after = connection.execute(
            text(
                f'SELECT {columns[table]} FROM "{table}" ORDER BY id'
                if "id" in names
                else f'SELECT {columns[table]} FROM "{table}" ORDER BY 1'
            )
        ).all()
        assert after == before[table], table
    assert (
        connection.execute(
            text(
                "SELECT active_version_id FROM project_route_family WHERE root_topic_id=:topic"
            ),
            params,
        ).scalar_one()
        == active
    )
    assert (
        connection.execute(
            text("SELECT count(*) FROM project_route_update")
        ).scalar_one()
        == 0
    )
    assert (
        connection.execute(
            text(
                "SELECT count(*) FROM project_training_input WHERE previous_version_id IS NOT NULL"
            )
        ).scalar_one()
        == 0
    )
    child = uuid.uuid4()
    connection.execute(
        text("INSERT INTO topic(id,user_id,created_at) VALUES(:child,:owner,now())"),
        {"child": child, "owner": owner},
    )
    connection.execute(
        text(
            "INSERT INTO project_route_update(topic_id,root_topic_id,previous_version_id) VALUES(:child,:topic,:active)"
        ),
        {"child": child, "topic": topic, "active": active},
    )
for operation in (
    "UPDATE project_route_update SET previous_version_id=previous_version_id",
    "DELETE FROM project_route_update",
):
    try:
        with isolated.begin() as connection:
            connection.execute(text(operation))
        raise AssertionError("update lineage mutation succeeded")
    except DBAPIError as error:
        assert "topic snapshots are immutable" in str(error)
print(  # noqa: T201 -- retained verification schema
    f"Preserved {sum(len(rows) for rows in before.values())} rows across {len(scopes)} tables; active pin and immutable lineage passed; retained schema={schema}"
)
