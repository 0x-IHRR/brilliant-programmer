"""Real isolated PostgreSQL dump/restore and credential revocation drill."""

import base64
import json
import os
import secrets
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path


def seed(kept: uuid.UUID, deleted: uuid.UUID) -> None:
    import procrastinate
    from pydantic import SecretStr
    from sqlmodel import Session

    from app.account_erasure.operations import initialize
    from app.core.db import engine
    from app.model_config.models import ModelConfig
    from app.model_config.service import encrypt
    from app.models import User
    from app.operations import state
    from app.project.models import ProjectRun
    from app.training.concept_models import ConceptHelp
    from app.training.evaluation_models import Evaluation, EvaluationAttempt
    from app.training.models import TrainingAttempt, TrainingRun
    from app.training.queue import DSN
    from app.training.review_models import ScoreReview
    from app.training.submission_models import Submission
    from app.training.topic_models import Topic, TopicJob

    destination = "https://synthetic.invalid/v1"
    with Session(engine) as session:
        for identity in (kept, deleted):
            session.add(
                User(
                    id=identity,
                    email=f"{identity}@synthetic.invalid",
                    hashed_password="synthetic-not-a-login",
                    email_verified=True,
                )
            )
        session.commit()
        config = ModelConfig(
            user_id=kept,
            service_url=destination,
            model_id="synthetic",
            encrypted_key=b"",
            key_version="v1",
        )
        config.encrypted_key = encrypt(config, SecretStr("synthetic-key"))
        session.add(config)
        active = TrainingRun(
            user_id=kept,
            config_version=config.version,
            destination=destination,
            model_id="synthetic",
            selection={},
            target={},
            status="running",
            attempts=2,
        )
        completed = TrainingRun(
            user_id=kept,
            config_version=config.version,
            destination=destination,
            model_id="synthetic",
            selection={},
            target={},
            candidate={"result": "kept"},
            status="completed",
            code="ok",
        )
        topic = Topic(user_id=kept)
        session.add_all([active, completed, topic])
        session.flush()
        project = ProjectRun(
            user_id=kept,
            url="https://github.com/synthetic/example",
            config_version=config.version,
            destination=destination,
            model_id="synthetic",
            status="running",
            snapshot={"checked": True},
        )
        topic_job = TopicJob(
            id=uuid.uuid4(),
            user_id=kept,
            topic_id=topic.id,
            input_text="synthetic",
            config_version=config.version,
            destination=destination,
            model_id="synthetic",
            status="running",
        )
        submission = Submission(
            run_id=active.id,
            answers=[{"private": "preserved"}],
            input_hash="synthetic-input",
            config_version=config.version,
            destination=destination,
            model_id="synthetic",
            status="needs_supplement",
        )
        evaluation = Evaluation(
            run_id=active.id,
            inputs={"private": "preserved"},
            case_snapshot={"result": "preserved"},
            sources=[],
            config_version=config.version,
            destination=destination,
            model_id="synthetic",
            status="needs_clarification",
        )
        review = ScoreReview(
            run_id=active.id,
            request_id=uuid.uuid4(),
            snapshot={"result": "preserved"},
            config_version=config.version,
            destination=destination,
            model_id="synthetic",
        )
        help_item = ConceptHelp(
            run_id=active.id,
            created_sequence=1,
            request={"private": "preserved"},
            config_version=config.version,
            destination=destination,
            model_id="synthetic",
        )
        session.add_all(
            [
                project,
                topic_job,
                submission,
                evaluation,
                review,
                help_item,
                TrainingAttempt(
                    run_id=completed.id,
                    number=1,
                    generation=0,
                    code="ok",
                    total_tokens=7,
                ),
                EvaluationAttempt(
                    run_id=active.id,
                    number=1,
                    code="unknown",
                    total_tokens=None,
                ),
            ]
        )
        session.flush()
        queue = procrastinate.App(
            connector=procrastinate.SyncPsycopgConnector(conninfo=DSN)
        )

        def placeholder(**_kwargs: str) -> None:
            raise AssertionError("restored jobs must never execute")

        jobs = (
            (active, "training.generate", {"run_id": str(active.id)}),
            (project, "project.analyze", {"run_id": str(project.id)}),
            (topic_job, "topic.analyze", {"topic_job_id": str(topic_job.id)}),
            (
                submission,
                "training.check_submission",
                {"submission_id": str(submission.id)},
            ),
            (evaluation, "training.evaluate", {"run_id": str(active.id)}),
            (review, "training.review", {"run_id": str(active.id)}),
            (help_item, "training.concept", {"help_id": str(help_item.id)}),
        )
        for item, name, arguments in jobs:
            task = queue.task(name=name)(placeholder)
            item.queue_job_id = task.configure(
                connection=session.connection().connection.driver_connection
            ).defer(**arguments)
            session.add(item)
        session.commit()
    initialize(live_upgrade=True)
    state.publish("ready")


def append_deletion(identity: uuid.UUID) -> None:
    from datetime import UTC, datetime

    from app.account_erasure import journal

    journal.append(identity, uuid.uuid4(), datetime.now(UTC), "synthetic-receipt")


def verify_rotation() -> None:
    from sqlmodel import Session, select

    from app.core.db import engine
    from app.model_config.models import ModelConfig
    from app.model_config.service import decrypt

    with Session(engine) as session:
        configs = session.exec(select(ModelConfig)).all()
        assert configs and all(config.key_version == "v2" for config in configs)
        assert all(
            decrypt(config).get_secret_value() == "synthetic-key" for config in configs
        )


def verify_blocked(identity: uuid.UUID) -> None:
    from fastapi import HTTPException
    from sqlmodel import Session

    from app.core.db import engine
    from app.training.gate import acquire

    with Session(engine) as session:
        try:
            acquire(session, identity, None)
        except HTTPException as error:
            assert error.status_code == 503
        else:
            raise AssertionError("version=None probe opened during restore")


def verify_restored(kept: uuid.UUID, deleted: uuid.UUID) -> None:
    from sqlalchemy import text
    from sqlmodel import Session

    from app.core.db import engine
    from app.model_config.models import ModelConfig
    from app.models import User
    from app.operations import state

    with Session(engine) as session:
        assert session.get(User, deleted) is None
        config = session.get(ModelConfig, kept)
        assert config and config.revoked and config.key_version == "v1"
        for table in (
            "training_run",
            "project_run",
            "topic_job",
            "training_submission",
            "training_evaluation",
            "score_review",
            "concept_help",
        ):
            active = session.execute(
                text(
                    f'SELECT count(*) FROM "{table}" '
                    "WHERE status NOT IN ('completed','failed','stopped','ready','deleted')"
                )
            ).scalar_one()
            assert active == 0, table
        assert (
            session.execute(
                text(
                    "SELECT candidate->>'result' FROM training_run WHERE status='completed'"
                )
            ).scalar_one()
            == "kept"
        )
        assert (
            session.execute(
                text("SELECT total_tokens FROM training_attempt WHERE code='ok'")
            ).scalar_one()
            == 7
        )
        assert (
            session.execute(
                text(
                    "SELECT count(*) FROM procrastinate_jobs WHERE status IN ('todo','doing')"
                )
            ).scalar_one()
            == 0
        )
        assert (
            session.execute(
                text("SELECT count(*) FROM procrastinate_jobs WHERE status='cancelled'")
            ).scalar_one()
            >= 7
        )
    assert state.phase() == "ready"


def parse_env(path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if line)


def command(
    arguments: list[str], *, env: dict[str, str], cwd: Path, data: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        arguments,
        cwd=cwd,
        env=env,
        input=data,
        capture_output=True,
        check=True,
    )


def main() -> None:
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        identities = [uuid.UUID(value) for value in sys.argv[2:]]
        if mode == "seed":
            seed(*identities)
        elif mode == "delete":
            append_deletion(*identities)
        elif mode == "rotation":
            verify_rotation()
        elif mode == "blocked":
            verify_blocked(*identities)
        elif mode == "restored":
            verify_restored(*identities)
        return

    backend = Path(__file__).resolve().parent.parent
    root = backend.parent
    runtime = parse_env(root / ".private/runtime.env")
    artifact = Path(tempfile.mkdtemp(prefix="bp-issue-33-", dir="/tmp"))
    state_root = artifact / "state"
    state_root.mkdir(mode=0o700)
    container = os.environ.get("OPERATIONS_DB_CONTAINER", "bp-issue-33-db-1")
    marker = uuid.uuid4().hex[:10]
    source = f"bp33_source_{marker}"
    restored = f"bp33_restored_{marker}"
    kept, deleted = uuid.uuid4(), uuid.uuid4()
    key_v1 = base64.b64encode(secrets.token_bytes(32)).decode()
    key_v2 = base64.b64encode(secrets.token_bytes(32)).decode()
    child_env = dict(os.environ)
    child_env.update(runtime)
    child_env.update(
        ACCOUNT_ERASURE_JOURNAL=str(state_root / "account-deletions.sqlite3"),
        OPERATIONS_ROOT=str(state_root),
        MODEL_ENCRYPTION_KEYS=json.dumps({"v1": key_v1}),
        MODEL_ACTIVE_KEY_VERSION="v1",
    )

    def database_env(name: str) -> dict[str, str]:
        return child_env | {
            "DATABASE_URL": f"postgresql://bp:{runtime['POSTGRES_PASSWORD']}@127.0.0.1:{runtime['DB_PORT']}/{name}"
        }

    for name in (source, restored):
        command(
            ["docker", "exec", container, "createdb", "-U", "bp", name],
            env=child_env,
            cwd=root,
        )
    source_env = database_env(source)
    command(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=source_env,
        cwd=backend,
    )
    command(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "seed",
            str(kept),
            str(deleted),
        ],
        env=source_env,
        cwd=backend,
    )
    dump = command(
        ["docker", "exec", container, "pg_dump", "-U", "bp", "-d", source, "-Fc"],
        env=child_env,
        cwd=root,
    ).stdout
    backup_id = (
        command(
            [sys.executable, "-m", "app.operations.admin", "store-backup"],
            env=source_env,
            cwd=backend,
            data=dump,
        )
        .stdout.decode()
        .strip()
    )
    backup = state_root / "backups" / f"{uuid.UUID(backup_id)}.dump"
    assert backup.read_bytes() == dump and backup.stat().st_mode & 0o777 == 0o600
    rotated_env = source_env | {
        "MODEL_ENCRYPTION_KEYS": json.dumps({"v1": key_v1, "v2": key_v2}),
        "MODEL_ACTIVE_KEY_VERSION": "v2",
    }
    command(
        [sys.executable, "-m", "app.operations.admin", "rotate-keys"],
        env=rotated_env,
        cwd=backend,
    )
    command(
        [sys.executable, str(Path(__file__).resolve()), "rotation"],
        env=rotated_env | {"MODEL_ENCRYPTION_KEYS": json.dumps({"v2": key_v2})},
        cwd=backend,
    )
    command(
        [sys.executable, str(Path(__file__).resolve()), "delete", str(deleted)],
        env=rotated_env,
        cwd=backend,
    )
    command(
        [
            "docker",
            "exec",
            "-i",
            container,
            "pg_restore",
            "-U",
            "bp",
            "-d",
            restored,
            "--no-owner",
            "--exit-on-error",
        ],
        env=child_env,
        cwd=root,
        data=dump,
    )
    restored_env = database_env(restored) | {
        "MODEL_ENCRYPTION_KEYS": json.dumps({"v1": key_v1, "v2": key_v2}),
        "MODEL_ACTIVE_KEY_VERSION": "v2",
    }
    command(
        [sys.executable, "-m", "app.operations.admin", "isolate"],
        env=restored_env,
        cwd=backend,
    )
    command(
        [sys.executable, str(Path(__file__).resolve()), "blocked", str(kept)],
        env=restored_env,
        cwd=backend,
    )
    failed = subprocess.run(
        [sys.executable, "-m", "app.operations.admin", "check"],
        cwd=backend,
        env=restored_env,
        capture_output=True,
    )
    assert failed.returncode != 0 and b"synthetic-key" not in failed.stderr
    (state_root / "restore.json").write_text("{")
    interrupted = subprocess.run(
        [sys.executable, "-m", "app.operations.admin", "finish-restore"],
        cwd=backend,
        env=restored_env,
        capture_output=True,
    )
    assert interrupted.returncode != 0
    from_state = state_root / "restore.json"
    assert from_state.read_text() == "{"
    exclusive = json.dumps({"phase": "restoring"})
    from_state.write_text(exclusive)
    command(
        [sys.executable, "-m", "app.operations.admin", "finish-restore"],
        env=restored_env,
        cwd=backend,
    )
    command(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "restored",
            str(kept),
            str(deleted),
        ],
        env=restored_env,
        cwd=backend,
    )
    command(
        [sys.executable, "-m", "app.operations.admin", "check"],
        env=restored_env,
        cwd=backend,
    )
    (artifact / "result.json").write_text(
        json.dumps(
            {
                "backup_bytes": len(dump),
                "databases": [source, restored],
                "outcome": "passed",
            },
            sort_keys=True,
        )
    )
    print(  # noqa: T201 - drill reports only its unique artifact directory
        f"backup/restore/key-rotation/replay passed; artifacts: {artifact}"
    )


if __name__ == "__main__":
    main()
