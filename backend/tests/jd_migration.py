"""Real 0022→JD migration retains an existing free-topic original and route."""

import os
import subprocess
import sys
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from app.core.config import settings
from app.core.db import engine

schema = "issue21_migration_" + uuid.uuid4().hex[:8]
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


migrate("0022_score_review")
with isolated.begin() as connection:
    run, owner, topic = connection.execute(
        text(
            "SELECT id,user_id,(selection->>'topic_id')::uuid FROM public.training_run WHERE selection->>'entry'='free_topic' AND formal_submitted_at IS NOT NULL ORDER BY created_at DESC LIMIT 1"
        )
    ).one()
    scopes = [
        ("user", "id=:owner"),
        ("topic", "id=:topic"),
        ("topic_version", "topic_id=:topic"),
        ("topic_job", "topic_id=:topic"),
        ("training_run", "id=:run"),
        ("training_submission", "run_id=:run"),
        ("practice_award", "run_id=:run"),
    ]
    before = {}
    for table, where in scopes:
        connection.execute(
            text(f'INSERT INTO "{table}" SELECT * FROM public."{table}" WHERE {where}'),
            {"run": run, "owner": owner, "topic": topic},
        )
        before[table] = (
            connection.execute(
                text(f'SELECT row_to_json(t) FROM "{table}" t ORDER BY 1::text')
            )
            .scalars()
            .all()
        )
migrate("head")
with isolated.begin() as connection:
    for table, _ in scopes:
        assert (
            connection.execute(
                text(f'SELECT row_to_json(t) FROM "{table}" t ORDER BY 1::text')
            )
            .scalars()
            .all()
            == before[table]
        )
    assert connection.execute(text("SELECT count(*) FROM jd_topic")).scalar() == 0
    job = connection.execute(text("SELECT id FROM topic_job LIMIT 1")).scalar_one()
    version = connection.execute(
        text("SELECT id FROM topic_version LIMIT 1")
    ).scalar_one()
    connection.execute(
        text("INSERT INTO jd_topic(topic_id) VALUES(:topic)"), {"topic": topic}
    )
    connection.execute(
        text(
            "INSERT INTO jd_document(id,topic_id,text) VALUES(:job,:topic,'controlled immutable JD')"
        ),
        {"job": job, "topic": topic},
    )
    connection.execute(
        text("INSERT INTO jd_analysis(document_id,snapshot) VALUES(:job,'{}')"),
        {"job": job},
    )
    connection.execute(
        text(
            "INSERT INTO jd_route(version_id,document_id,snapshot) VALUES(:version,:job,'{}')"
        ),
        {"version": version, "job": job},
    )
for sql in [
    "UPDATE jd_document SET text='overwrite'",
    "DELETE FROM jd_analysis",
    "UPDATE jd_route SET snapshot='{}'",
    "DELETE FROM jd_topic",
]:
    try:
        with isolated.begin() as connection:
            connection.execute(text(sql))
        raise AssertionError("JD provenance mutation succeeded")
    except DBAPIError as error:
        assert "topic snapshots are immutable" in str(error)
print(  # noqa: T201 -- retained verification schema
    f"Preserved {sum(len(v) for v in before.values())} original rows across 7 tables; 4 JD immutable guards; retained schema={schema}"
)
