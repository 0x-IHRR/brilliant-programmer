"""One evaluation can be started from consented submission or existing history."""

import procrastinate
from sqlmodel import Session, col, select

from app.model_config.models import ModelConfig
from app.training.evaluation_models import Evaluation
from app.training.evaluation_schema import evaluation_inputs
from app.training.models import TrainingRun
from app.training.queue import DSN
from app.training.submission_models import Submission


def enqueue(session: Session, item: Evaluation) -> None:
    from app.training.evaluation_worker import evaluate

    app = procrastinate.App(connector=procrastinate.SyncPsycopgConnector(conninfo=DSN))
    task = app.task(name="training.evaluate")(evaluate.func)
    item.queue_job_id = task.configure(
        connection=session.connection().connection.driver_connection,
        lock="evaluation:" + str(item.run_id),
    ).defer(run_id=str(item.run_id))
    session.add(item)


def create_evaluation(
    session: Session, run: TrainingRun, config: ModelConfig
) -> Evaluation:
    from app.training.evaluation_worker import freeze

    existing = session.get(Evaluation, run.id)
    if existing:
        return existing
    submissions = list(
        session.exec(
            select(Submission)
            .where(
                Submission.run_id == run.id, col(Submission.practice_help_id).is_(None)
            )
            .order_by(col(Submission.sequence))
        ).all()
    )
    inputs = evaluation_inputs(submissions)
    assert run.candidate
    item = Evaluation(
        run_id=run.id,
        inputs=inputs.model_dump(mode="json"),
        case_snapshot=run.candidate,
        sources=run.sources,
        config_version=config.version,
        destination=config.service_url,
        model_id=config.model_id,
    )
    if inputs.clarification_used:
        freeze(session, item)
    session.add(item)
    session.flush()
    enqueue(session, item)
    return item
