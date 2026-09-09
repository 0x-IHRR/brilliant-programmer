"""Real isolated 0019→0020 migration retains an existing completed original round."""

import os
import subprocess
import sys
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.db import engine

schema = "issue20_migration_" + uuid.uuid4().hex[:8]
with engine.begin() as c:
    c.execute(text(f'CREATE SCHEMA "{schema}"'))
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


migrate("0019_first_boss")
with isolated.begin() as c:
    run, owner = c.execute(
        text(
            "SELECT id,user_id FROM public.training_run WHERE formal_submitted_at IS NOT NULL ORDER BY created_at DESC LIMIT 1"
        )
    ).one()
    tables = [
        ("user", "id=:owner"),
        ("training_run", "id=:run"),
        ("training_submission", "run_id=:run"),
        ("practice_award", "run_id=:run"),
    ]
    before = {}
    for table, where in tables:
        c.execute(
            text(f'INSERT INTO "{table}" SELECT * FROM public."{table}" WHERE {where}'),
            {"run": run, "owner": owner},
        )
        before[table] = (
            c.execute(text(f'SELECT row_to_json(t) FROM "{table}" t ORDER BY 1::text'))
            .scalars()
            .all()
        )
migrate("head")
with isolated.begin() as c:
    for table, _ in tables:
        assert (
            c.execute(text(f'SELECT row_to_json(t) FROM "{table}" t ORDER BY 1::text'))
            .scalars()
            .all()
            == before[table]
        )
    assert c.execute(text("SELECT count(*) FROM topic")).scalar() == 0
    assert c.execute(text("SELECT count(*) FROM topic_case")).scalar() == 0
    topic, version = uuid.uuid4(), uuid.uuid4()
    c.execute(
        text("INSERT INTO topic(id,user_id,created_at) VALUES(:id,:owner,now())"),
        {"id": topic, "owner": owner},
    )
    c.execute(
        text("INSERT INTO topic_version(id,topic_id,snapshot) VALUES(:id,:topic,'{}')"),
        {"id": version, "topic": topic},
    )
try:
    with isolated.begin() as c:
        c.execute(text("UPDATE topic_version SET snapshot='{}'"))
    raise AssertionError("immutable snapshot changed")
except Exception as error:
    assert "topic snapshots are immutable" in str(error)
print(  # noqa: T201 -- named retained verification resource
    f"Migration retained old row payloads; immutable snapshot verified; schema={schema}"
)
with isolated.begin() as c:
    c.execute(
        text("INSERT INTO topic_case(run_id,candidate) VALUES(:run,'{}')"), {"run": run}
    )
for sql, expected in [
    ("UPDATE topic_case SET candidate='{}'", "topic snapshots are immutable"),
    (
        "UPDATE training_run SET selection=jsonb_set(selection::jsonb,'{goal}','\"changed\"')::json WHERE selection->>'entry'='free_topic'",
        "confirmed topic goal is immutable",
    ),
]:
    try:
        with isolated.begin() as c:
            result = c.execute(text(sql))
            assert result.rowcount == 0, "protected fact changed"
    except Exception as error:
        assert expected in str(error)
