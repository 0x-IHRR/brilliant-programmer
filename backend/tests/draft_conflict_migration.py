"""Isolated 0013 -> 0014 witness using synthetic records already in this test DB."""

import os
import subprocess
import sys
import uuid

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.main import app  # noqa: F401 -- register existing model metadata
from app.model_config.service import lock_owner
from app.training import draft_collection as collections
from app.training.draft_models import TrainingDraft
from app.training.practice_models import PracticeDraft

schema = "issue14_migration_" + uuid.uuid4().hex[:8]
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


migrate("0013_config_revocation")
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
migrate("0014_draft_conflicts")
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
    assert (
        connection.execute(text("SELECT count(*) FROM draft_collection")).scalar() == 0
    )
# Exercise the real lazy import under its existing lock in this isolated schema.


with Session(isolated) as session:
    originals = session.exec(select(TrainingDraft)).scalars().all()
    practices = session.exec(select(PracticeDraft)).scalars().all()
    assert originals and practices
    for item in [*originals, *practices]:
        run = session.get(collections.TrainingRun, item.run_id)
        lock_owner(session, run.user_id)
        collections.lock_run(session, run.id)
        state = collections.load(session, run.id, getattr(item, "help_id", None))
        assert len(state.versions) == 1 and state.current == item.version
        assert state.versions[0].progress.model_dump(mode="json") == item.progress
        assert state.versions[0].request_id == item.request_id
    session.commit()
print(  # noqa: T201 -- synthetic migration recovery location/counts, never credentials
    schema,
    {table: len(rows) for table, rows in before.items()},
    "preserved; original/practice snapshots imported without resetting identities",
)
isolated.dispose()
