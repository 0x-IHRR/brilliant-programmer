"""Real 0024→project migration retains existing original answers, awards and route."""

import os
import subprocess
import sys
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from app.core.config import settings
from app.core.db import engine

schema = "issue23_migration_" + uuid.uuid4().hex[:8]
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


migrate("0024_jd_route")
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
                text(f'SELECT row_to_json(t) FROM "{table}" t ORDER BY row_to_json(t)::text')
            )
            .scalars()
            .all()
        )
migrate("head")
with isolated.begin() as connection:
    for table, _ in scopes:
        assert (
            connection.execute(
                text(f'SELECT row_to_json(t) FROM "{table}" t ORDER BY row_to_json(t)::text')
            )
            .scalars()
            .all()
            == before[table]
        )
    assert connection.execute(text("SELECT count(*) FROM project_topic")).scalar() == 0
    job = connection.execute(text("SELECT id FROM topic_job LIMIT 1")).scalar_one()
    version = connection.execute(
        text("SELECT id FROM topic_version LIMIT 1")
    ).scalar_one()
    project = uuid.uuid4()
    connection.execute(
        text("""INSERT INTO project_run
        (id,user_id,url,reanalyze,config_version,destination,model_id,status,code,message,
         stop_requested,acquisition_done,source_requests,source_bytes,attempts,generation,generation_attempts,created_at)
        VALUES(:project,:owner,'https://github.com/example/example',false,:config,'https://provider.example.com','controlled','failed','insufficient_sources','migration fixture',false,false,0,0,0,0,0,now())"""),
        {"project": project, "owner": owner, "config": uuid.uuid4()},
    )
    connection.execute(
        text(
            "INSERT INTO project_topic(topic_id,project_run_id) VALUES(:topic,:project)"
        ),
        {"topic": topic, "project": project},
    )
    connection.execute(
        text(
            "INSERT INTO project_training_input(id,topic_id,project_run_id,snapshot,project_map) VALUES(:job,:topic,:project,'{}','{}')"
        ),
        {"job": job, "topic": topic, "project": project},
    )
    connection.execute(
        text(
            "INSERT INTO project_training_version(version_id,input_id,snapshot) VALUES(:version,:job,'{}')"
        ),
        {"version": version, "job": job},
    )
    connection.execute(
        text(
            "INSERT INTO project_training_materials(run_id,origins) VALUES(:run,'[]')"
        ),
        {"run": run},
    )
for table in (
    "project_topic",
    "project_training_input",
    "project_training_version",
    "project_training_materials",
):
    for operation in (
        f"UPDATE {table} SET "
        + (
            "topic_id=topic_id"
            if table == "project_topic"
            else "snapshot=snapshot"
            if table in {"project_training_input", "project_training_version"}
            else "origins=origins"
        ),
        f"DELETE FROM {table}",
    ):
        try:
            with isolated.begin() as connection:
                connection.execute(text(operation))
            raise AssertionError("project provenance mutation succeeded")
        except DBAPIError as error:
            assert "topic snapshots are immutable" in str(error)
print(  # noqa: T201 -- retained verification schema
    f"Preserved {sum(len(v) for v in before.values())} original rows across 7 tables; 8 project immutable guards; retained schema={schema}"
)
