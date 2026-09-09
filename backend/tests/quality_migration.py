"""Real isolated 0024 -> 0025, retaining legacy answers and unknown delivery facts."""

import json
import os
import re
import subprocess
import sys
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.db import engine

schema = "issue29_migration_" + uuid.uuid4().hex[:8]
with engine.begin() as connection:
    connection.execute(text(f'CREATE SCHEMA "{schema}"'))
url = make_url(str(settings.DATABASE_URL)).update_query_dict(
    {"options": "-csearch_path=" + schema}
)
isolated = create_engine(url, hide_parameters=True)
env = {**os.environ, "DATABASE_URL": url.render_as_string(hide_password=False)}


def run(args):
    result = subprocess.run([sys.executable, *args], env=env, capture_output=True)
    if result.returncode:
        kinds = re.findall(rb"^([A-Za-z_.]*(?:Error|Exception)):", result.stderr, re.M)
        raise AssertionError("isolated command failed: " + (kinds[-1].decode() if kinds else "unknown") + "; private parameters omitted")


run(["-m", "alembic", "upgrade", "0024_jd_route"])
run(
    [
        "-c",
        """
from datetime import UTC, datetime
import app.main
import uuid
from sqlmodel import Session
from app.core.db import engine
from app.models import User
from app.training.models import TrainingRun
from app.training.evaluation_models import Evaluation
from app.training.evaluation_schema import evaluation_inputs
from app.training.independent_models import IndependentObservation
from app.training.independent_novelty import case_digest
from app.training.submission_models import PracticeAward
from app.capabilities.evidence_models import OriginalOrder
from tests.test_evaluation_schema import example
with Session(engine) as session:
 owner=User(email="legacy-"+uuid.uuid4().hex+"@example.com", hashed_password="synthetic-nonlogin", email_verified=True)
 session.add(owner); session.flush()
 for position, outcome in enumerate(["independent_pass_candidate", "pending_delivery", "ordinary_completed"],1):
  case,sources,original,grading=example("choice")
  run=TrainingRun(id=original.run_id,user_id=owner.id,config_version=original.config_version,destination=original.destination,model_id=original.model_id,target=case.target.model_dump(),selection={},candidate=case.model_dump(),sources=[s.model_dump() for s in sources],status="completed",launch_mode="practice" if outcome == "ordinary_completed" else "independent",event_sequence=4,formal_submitted_at=datetime.now(UTC))
  session.add(run);session.flush();session.add(original);session.flush()
  session.add(OriginalOrder(original_id=original.id,user_id=owner.id,position=position,submitted_at=original.created_at,source="user_locked"))
  session.add(PracticeAward(run_id=run.id,submission_id=original.id,user_id=owner.id))
  session.add(Evaluation(run_id=run.id,config_version=run.config_version,destination=run.destination,model_id=run.model_id,case_snapshot=case.model_dump(),sources=run.sources,inputs=evaluation_inputs([original]).model_dump(mode="json"),result=grading,status="completed",frozen_sequence=3,frozen_at=datetime.now(UTC)))
  if outcome != "ordinary_completed": session.add(IndependentObservation(run_id=run.id,sequence=4,frozen_sequence=3,original_id=original.id,case_digest=case_digest(case),target=case.target.model_dump(),outcome=outcome))
 session.commit()
""",
    ]
)


def facts():
    with isolated.connect() as connection:
        return {
            table: connection.execute(
                text(f'SELECT to_jsonb(t) FROM "{table}" t ORDER BY to_jsonb(t)::text')
            )
            .scalars()
            .all()
            for table in (
                "user",
                "training_run",
                "training_submission",
                "training_evaluation",
                "capability_original_order",
                "independent_observation",
                "practice_award",
            )
        }


before = facts()
run(["-m", "alembic", "upgrade", "head"])
assert facts() == before
with isolated.connect() as connection:
    rows = connection.execute(
        text(
            "SELECT d.status,d.binding,e.config_version,o.outcome FROM quality_disposition d JOIN training_evaluation e ON e.run_id=d.run_id JOIN independent_observation o ON o.run_id=e.run_id"
        )
    ).all()
    assert len(rows) == 1 and rows[0].status == "unverified"
    assert connection.execute(text("SELECT count(*) FROM quality_disposition")).scalar_one() == 2
    assert rows[0].binding["config_version"] == str(rows[0].config_version)
    assert rows[0].outcome == "independent_pass_candidate"
    assert (
        connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        == "0025_quality_admission"
    )
run(["-m", "alembic", "upgrade", "head"])
assert facts() == before
run(["-c", """
import uuid
import app.main
from sqlmodel import Session, select
from app.core.db import engine
from app.model_config.service import lock_owner
from app.quality.models import QualityDisposition
from app.training.evaluation_models import Evaluation
from app.training.independent_service import record_frozen
from app.training.models import TrainingRun
from app.training.schema import Source
from tests.test_quality_api import report_for, publish
with Session(engine) as session:
 run = session.exec(select(TrainingRun).where(TrainingRun.launch_mode == "practice")).one()
 identity, owner = run.id, run.user_id
 config = {"version": str(run.config_version), "service_url": run.destination, "model_id": run.model_id}
 sources = [Source.model_validate(s) for s in run.sources]
 original = session.get(QualityDisposition, (identity, "original")).model_dump()
 assert original["status"] == "unverified"
failed, _ = report_for(owner, config, failed=True, sources=sources)
publish(failed)
for step in range(2):
 if step:
  retest, _ = report_for(owner, config, sources=sources, supersedes=failed.artifact_id)
  publish(retest)
 with Session(engine) as session:
  lock_owner(session, owner)
  record_frozen(session, session.get(TrainingRun, identity), session.get(Evaluation, identity))
  session.commit()
  assert session.get(QualityDisposition, (identity, "original")).model_dump() == original
"""])
assert facts() == before
print(  # noqa: T201
    json.dumps(
        {
            "schema": schema,
            "legacy_facts_unchanged": True,
            "pending_not_certified": True,
            "ordinary_future_reports_cannot_rewrite": True,
            "single_head": "0025_quality_admission",
        }
    )
)
