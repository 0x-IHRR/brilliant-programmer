"""Isolated old public/private/failed rounds; never migrate another test DB."""

import os
import subprocess
import sys
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session

from app.capabilities.catalog import EvidenceKey
from app.capabilities.unlocks import open_unit
from app.core.config import settings
from app.core.db import engine
from app.model_config.service import lock_owner

schema = "issue18_migration_" + uuid.uuid4().hex[:8]
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


migrate("0016_capability_evidence")
with isolated.begin() as connection:
    identity = connection.execute(
        text(
            "SELECT id FROM public.training_run WHERE json_typeof(candidate)='object' LIMIT 1"
        )
    ).scalar_one()
    for table in ["user", "training_run"]:
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
    columns = (
        connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns WHERE table_schema=:schema AND table_name='training_run' ORDER BY ordinal_position"
            ),
            {"schema": schema},
        )
        .scalars()
        .all()
    )
    public_tier = connection.execute(text("SELECT target->>'difficulty' FROM training_run WHERE id=:id"), {"id": identity}).scalar_one()
    other_tiers = [tier for tier in ["基础", "进阶", "综合"] if tier != public_tier]
    for state, tier in zip(["failed", "running"], other_tiers, strict=True):
        values = ",".join(
            ":newid"
            if c == "id"
            else "'null'::json"
            if c == "candidate"
            else "json_build_object('capability_id', target->>'capability_id', 'difficulty', CAST(:tier AS text), 'background_id', target->>'background_id')"
            if c == "target"
            else ":state"
            if c == "status"
            else f'"{c}"'
            for c in columns
        )
        connection.execute(
            text(
                f"INSERT INTO training_run SELECT {values} FROM training_run WHERE id=:id"
            ),
            {"newid": uuid.uuid4(), "state": state, "tier": tier, "id": identity},
        )
    before = (
        connection.execute(
            text("SELECT to_jsonb(t)::text FROM training_run t ORDER BY id")
        )
        .scalars()
        .all()
    )
migrate("head")
with isolated.connect() as connection:
    assert (
        connection.execute(
            text("SELECT to_jsonb(t)::text FROM training_run t ORDER BY id")
        )
        .scalars()
        .all()
        == before
    )
    openings = connection.execute(text("SELECT * FROM opened_unit")).mappings().all()
    assert len(openings) == 1 and openings[0]["source"] == "legacy_public_case"
    assert openings[0]["evidence_ids"] == []
    legacy = openings[0]
# Reopening the same legacy public unit goes through the actual owner boundary,
# even without new independent prerequisite evidence; it creates no duplicate.
with Session(isolated) as session:
    lock_owner(session, legacy["user_id"])
    result = open_unit(session, legacy["user_id"], EvidenceKey.model_validate({
        key: legacy[key] for key in ["capability_id", "difficulty", "background_id"]
    }))
    assert result.opened
    session.commit()
for statement in ["UPDATE opened_unit SET source='changed'", "DELETE FROM opened_unit"]:
    try:
        with isolated.begin() as connection:
            connection.execute(text(statement))
    except DBAPIError as error:
        assert "learning-unit openings are immutable" in str(error.orig)
    else:
        raise AssertionError("opening must remain immutable")
with isolated.connect() as connection:
    assert connection.execute(text("SELECT count(*) FROM opened_unit")).scalar_one() == 1
print(  # noqa: T201 -- synthetic schema recovery location, no credentials
    schema,
    "3 old rounds preserved; exactly 1 public unit imported, private/failed JSON null excluded",
)
isolated.dispose()
