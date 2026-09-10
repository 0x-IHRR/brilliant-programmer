"""Synthetic old records: real 0027 -> current head, no stamp or source schema mutation."""

import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session

from app.capabilities.evidence_models import OriginalOrder
from app.core.config import settings
from app.core.db import engine
from app.core.security import get_password_hash
from app.deletion.service import erase, preview
from app.models import User
from app.project.models import ProjectRun
from app.project.training_models import (
    ProjectInput,
    ProjectMaterials,
    ProjectTopic,
    ProjectVersion,
)
from app.training.concept_models import ConceptHelp, HelpDelivery
from app.training.draft_collection import DraftCollection
from app.training.draft_models import TrainingDraft
from app.training.evaluation_models import Evaluation
from app.training.independent_models import IndependentWork
from app.training.models import TrainingRun
from app.training.practice_models import PracticeDraft
from app.training.submission_models import PracticeAward, Submission
from app.training.topic_models import Topic, TopicJob, TopicVersion

schema = "issue31_migration_" + uuid.uuid4().hex[:8]
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
    if result.returncode:
        raise AssertionError("isolated migration failed; connection parameters omitted")


migrate("0027_project_updates")
with Session(isolated) as session:
    owner = User(
        email=uuid.uuid4().hex + "@example.com",
        hashed_password=get_password_hash("synthetic-migration-password"),
        email_verified=True,
    )
    session.add(owner)
    session.flush()
    owner_id = owner.id
    topic = Topic(user_id=owner.id)
    session.add(topic)
    session.flush()
    project = ProjectRun(
        user_id=owner.id,
        url="https://github.com/example/synthetic",
        config_version=uuid.uuid4(),
        destination="https://example.com/v1",
        model_id="fake",
        status="completed",
        snapshot={"fragments": [{"text": "synthetic old source"}]},
        project_map={},
    )
    session.add(project)
    session.flush()
    project_id = project.id
    job = TopicJob(
        id=uuid.uuid4(),
        topic_id=topic.id,
        user_id=owner.id,
        input_text="synthetic old source",
        config_version=project.config_version,
        destination=project.destination,
        model_id="fake",
        status="completed",
    )
    session.add(job)
    session.flush()
    version = TopicVersion(
        id=uuid.uuid4(), topic_id=topic.id, snapshot={"old": "source"}
    )
    session.add(version)
    session.add(ProjectTopic(topic_id=topic.id, project_run_id=project.id))
    session.add(
        ProjectInput(
            id=job.id,
            topic_id=topic.id,
            project_run_id=project.id,
            snapshot=project.snapshot,
            project_map={},
        )
    )
    session.flush()
    session.add(
        ProjectVersion(
            version_id=version.id, input_id=job.id, snapshot={"old": "source"}
        )
    )
    run = TrainingRun(
        user_id=owner.id,
        config_version=project.config_version,
        destination=project.destination,
        model_id="fake",
        status="completed",
        selection={"topic_id": str(topic.id)},
        target={"catalog": "stable identity"},
        candidate={"old": "case"},
        sources=[{"text": "synthetic old source"}],
        formal_submitted_at=datetime.now(UTC),
    )
    session.add(run)
    session.flush()
    run_id = run.id
    original = Submission(
        run_id=run.id,
        sequence=1,
        config_version=run.config_version,
        destination=run.destination,
        model_id="fake",
        answers=[{"reason": "synthetic old answer"}],
        input_hash="synthetic",
        status="completed",
    )
    session.add(original)
    session.flush()
    session.add(
        OriginalOrder(
            original_id=original.id,
            user_id=owner.id,
            position=1,
            submitted_at=original.created_at,
        )
    )
    session.add(
        PracticeAward(run_id=run.id, submission_id=original.id, user_id=owner.id)
    )
    session.add(
        ProjectMaterials(run_id=run.id, origins=[{"quote": "synthetic old source"}])
    )
    session.add(
        IndependentWork(run_id=run.id, history=[{"run_id": str(run.id), "old": "case"}])
    )
    session.add(
        Evaluation(
            run_id=run.id,
            inputs={"old": "answer"},
            case_snapshot={"old": "case"},
            sources=run.sources,
            config_version=run.config_version,
            destination=run.destination,
            model_id="fake",
            status="completed",
            frozen_sequence=2,
            frozen_at=datetime.now(UTC),
            result={"old": "feedback"},
        )
    )
    help_item = ConceptHelp(
        run_id=run.id,
        created_sequence=3,
        config_version=run.config_version,
        destination=run.destination,
        model_id="fake",
        request={"old": "request"},
        content={"old": "help"},
        status="ready",
    )
    session.add(help_item)
    session.flush()
    session.add(
        HelpDelivery(
            help_id=help_item.id,
            run_id=run.id,
            sequence=4,
            exposure_sequence=4,
            status="delivered",
            delivered_text="old help",
            direction="neutral",
            content_hash="synthetic",
        )
    )
    for row in (
        TrainingDraft(
            run_id=run.id,
            version=uuid.uuid4(),
            request_id=uuid.uuid4(),
            saved_at=datetime.now(UTC),
            progress={"old": "draft"},
        ),
        PracticeDraft(
            help_id=help_item.id,
            run_id=run.id,
            version=uuid.uuid4(),
            request_id=uuid.uuid4(),
            saved_at=datetime.now(UTC),
            progress={"old": "practice draft"},
        ),
        DraftCollection(
            scope_key=str(run.id) + ":original",
            run_id=run.id,
            data={"old": "conflict history"},
        ),
    ):
        session.add(row)
    session.commit()

tables = [
    "user",
    "topic",
    "topic_job",
    "topic_version",
    "project_run",
    "project_topic",
    "project_training_input",
    "project_training_version",
    "project_training_materials",
    "training_run",
    "training_submission",
    "practice_award",
    "capability_original_order",
    "training_evaluation",
    "independent_work",
    "concept_help",
    "help_delivery",
    "training_draft",
    "practice_draft",
    "draft_collection",
]


def snapshots():
    with isolated.connect() as connection:
        return {
            table: connection.execute(
                text(
                    f'SELECT row_to_json(r) FROM "{table}" r ORDER BY row_to_json(r)::text'
                )
            )
            .scalars()
            .all()
            for table in tables
        }


before = snapshots()
migrate("head")
assert snapshots() == before
checks = [
    "UPDATE training_submission SET answers='[]'",
    "UPDATE training_evaluation SET inputs='{}'",
    "UPDATE practice_award SET points=points+10",
    "UPDATE capability_original_order SET position=position+1",
    "UPDATE help_delivery SET delivered_text=''",
    "UPDATE topic_version SET snapshot='{}'",
    "UPDATE project_training_input SET snapshot='{}'",
    "UPDATE project_training_version SET snapshot='{}'",
]
for command in checks:
    try:
        with isolated.begin() as connection:
            connection.execute(text(command))
    except DBAPIError:
        pass
    else:
        raise AssertionError(
            "old immutable protection was weakened: " + command.split()[1]
        )
with Session(isolated) as session:
    receipt, _ = preview(
        session, owner_id, "project", project_id, "synthetic-migration-password"
    )
    assert erase(session, owner_id, receipt.id).completed_at
with Session(isolated) as session:
    assert session.get(TrainingRun, run_id).candidate is None
    assert session.get(Evaluation, run_id).inputs == {}
    assert session.get(PracticeAward, run_id).points == 10
    assert session.get(ProjectRun, project_id).snapshot is None
# Old exact source/answer SQL replay cannot restore empty fields even with the
# original object identity. Markers remain available to future restore tooling.
for table, column in [
    ("training_run", "candidate"),
    ("training_submission", "answers"),
    ("project_training_input", "snapshot"),
]:
    try:
        with isolated.begin() as connection:
            connection.execute(
                text(f"UPDATE {table} SET {column} = CAST(:value AS json)"),
                {
                    "value": '["old answer"]'
                    if column == "answers"
                    else '{"old":"source"}'
                },
            )
    except DBAPIError:
        pass
    else:
        raise AssertionError("old identity replay restored " + table)
assert snapshots()["user"] == before["user"]
assert snapshots()["practice_award"] == before["practice_award"]
assert snapshots()["capability_original_order"] == before["capability_original_order"]
print(  # noqa: T201 - standalone validation report, no private values
    f"{schema}: 20 old tables unchanged across 0027→current head; 8 immutable guards; scoped erasure; 3 replay rejections; user/award/order unchanged"
)
isolated.dispose()
