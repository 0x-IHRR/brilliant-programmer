"""Real psycopg/SQLAlchemy transaction and native worker recovery contract."""

import procrastinate
from sqlalchemy import text
from sqlmodel import Session

from app.core.db import engine
from app.training.queue import DSN


def test_external_connection_transaction():
    app = procrastinate.App(connector=procrastinate.SyncPsycopgConnector(conninfo=DSN))

    @app.task(name="test.transaction")
    async def task():
        pass

    with engine.begin() as connection:
        if not connection.exec_driver_sql(
            "SELECT to_regclass('procrastinate_jobs')"
        ).scalar():
            connection.connection.driver_connection.execute(
                app.schema_manager.get_schema()
            )
    with Session(engine) as session:
        native = session.connection().connection.driver_connection
        job_id = task.configure(connection=native).defer()
        assert (
            session.execute(
                text("SELECT id FROM procrastinate_jobs WHERE id=:id"), {"id": job_id}
            ).scalar()
            == job_id
        )
        session.rollback()
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT id FROM procrastinate_jobs WHERE id=:id"), {"id": job_id}
            ).scalar()
            is None
        )
    with Session(engine) as session:
        job_id = task.configure(
            connection=session.connection().connection.driver_connection
        ).defer()
        session.commit()
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT status FROM procrastinate_jobs WHERE id=:id"),
                {"id": job_id},
            ).scalar()
            == "todo"
        )
    app.open()
    app.job_manager.cancel_job_by_id(job_id)
    app.close()
