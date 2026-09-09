import asyncio
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel import Session, col, select

from app.capabilities.catalog import CATALOG, EvidenceKey
from app.core.db import engine
from app.model_config.connection import BACKOFF_SECONDS, CancelledCall, ProbeError
from app.model_config.service import (
    cancelled_by_revocation,
    current_for_result,
    lock_owner,
)
from app.project.worker import reconcile_failed_projects
from app.training.concept_worker import reconcile_concepts
from app.training.evaluation_worker import reconcile_failed_evaluations
from app.training.gate import call_credential
from app.training.generation import generate
from app.training.models import TrainingAttempt, TrainingRun
from app.training.queue import queue
from app.training.review_worker import recover_reviews
from app.training.schema import Source, scenario_fingerprint, validate_candidate
from app.training.sources import acquire_source
from app.training.submission_worker import (  # noqa: F401
    check_submission,
    reconcile_failed_submissions,
)
from app.training.topic_worker import reconcile_topics

TERMINAL = {"completed", "failed", "stopped"}


def finish_stop(run_id: uuid.UUID, job_id: int | None) -> None:
    with Session(engine) as session:
        initial = session.get(TrainingRun, run_id)
        if not initial:
            return
        lock_owner(session, initial.user_id)
        run = session.exec(
            select(TrainingRun)
            .where(TrainingRun.id == run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one()
        if (
            run.queue_job_id != job_id
            or run.status != "stopping"
            or not run.stop_requested
        ):
            return
        run.status, run.code, run.message = (
            "stopped",
            "stopped",
            "已停止后续调用；已有成果和实际用量保留",
        )
        session.add(run)
        session.commit()


def reconcile_stops() -> None:
    with Session(engine) as session:
        pending = [
            (r.id, r.queue_job_id)
            for r in session.exec(
                select(TrainingRun).where(
                    TrainingRun.status == "stopping",
                    col(TrainingRun.stop_requested).is_(True),
                )
            ).all()
        ]
    for identity, job_id in pending:
        finish_stop(identity, job_id)
    with engine.connect() as connection:
        failed = connection.execute(
            text("""SELECT r.id, r.queue_job_id FROM training_run r
            JOIN procrastinate_jobs j ON j.id=r.queue_job_id
            WHERE r.launch_mode='independent' AND r.status IN ('queued','running')
            AND j.status IN ('failed','aborted','cancelled') LIMIT 100""")
        ).all()
    for identity, job_id in failed:
        finish(
            identity,
            "internal_failure",
            "后台未完成；原记录及预算保留，可主动重试",
            job_id,
        )


def read_run(run_id: uuid.UUID) -> TrainingRun:
    with Session(engine) as session:
        run = session.get(TrainingRun, run_id)
        if run is None:
            raise ValueError("missing training")
        return run


def last_attempt(run_id: uuid.UUID) -> TrainingAttempt | None:
    with Session(engine) as session:
        return session.exec(
            select(TrainingAttempt)
            .where(TrainingAttempt.run_id == run_id)
            .order_by(col(TrainingAttempt.number).desc())
        ).first()


def finish(
    run_id: uuid.UUID, code: str, message: str, job_id: int | None = None
) -> None:
    with Session(engine) as session:
        run = session.exec(
            select(TrainingRun).where(TrainingRun.id == run_id).with_for_update()
        ).one()
        # Acceptance/stop/failure may commit before a late cancellation unwinds.
        # The task lock makes that terminal fact authoritative for every caller.
        if run.status in TERMINAL or (
            job_id is not None and run.queue_job_id != job_id
        ):
            return
        if cancelled_by_revocation(session, run.user_id, run.config_version, code):
            run.stop_requested = True
            code = "configuration_revoked"
        if run.candidate:
            run.status = "stopped" if run.stop_requested else "completed"
        else:
            run.status = "stopped" if run.stop_requested else "failed"
        run.code, run.message = code, message
        session.add(run)
        session.commit()


def begin_attempt(
    run_id: uuid.UUID, job_id: int | None = None
) -> TrainingAttempt | None:
    with Session(engine) as session:
        run = session.exec(
            select(TrainingRun).where(TrainingRun.id == run_id).with_for_update()
        ).one()
        if (
            (job_id is not None and run.queue_job_id != job_id)
            or run.stop_requested
            or run.status in TERMINAL
            or run.attempts >= 6
            or run.generation_attempts >= 3
        ):
            return None
        run.status, run.code, run.message = (
            "running",
            "generating",
            "模型正在生成并核对候选",
        )
        run.attempts += 1
        run.generation_attempts += 1
        attempt = TrainingAttempt(
            run_id=run.id, number=run.attempts, generation=run.generation
        )
        session.add(run)
        session.add(attempt)
        session.commit()
        session.refresh(attempt)
        return attempt


def record_attempt(
    attempt_id: uuid.UUID, code: str, counts: dict[str, int | None]
) -> None:
    with Session(engine) as session:
        attempt = session.get(TrainingAttempt, attempt_id)
        assert attempt
        attempt.code = code
        for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
            setattr(attempt, name, counts.get(name))
        session.add(attempt)
        session.commit()


def save_sources(run_id: uuid.UUID, sources: list[Source]) -> None:
    with Session(engine) as session:
        run = session.exec(
            select(TrainingRun).where(TrainingRun.id == run_id).with_for_update()
        ).one()
        if run.sources or run.candidate or run.stop_requested:
            return
        run.sources = [source.model_dump() for source in sources]
        session.add(run)
        session.commit()


def accept_candidate(run_id: uuid.UUID, raw: str, key: str) -> bool:
    with Session(engine) as session:
        run = session.exec(
            select(TrainingRun).where(TrainingRun.id == run_id).with_for_update()
        ).one()
        if run.candidate:
            return True
        current_for_result(session, run.user_id, run.config_version)
        candidate = validate_candidate(
            raw,
            EvidenceKey.model_validate(run.target),
            [Source.model_validate(s) for s in run.sources],
            key,
        )
        fingerprint = scenario_fingerprint(candidate)
        previous = session.exec(
            select(TrainingRun.id).where(
                TrainingRun.user_id == run.user_id,
                TrainingRun.scenario_hash == fingerprint,
                TrainingRun.id != run.id,
            )
        ).first()
        if previous:
            raise ValueError("repeated scenario")
        # call_credential's separate Session already holds User until this
        # acceptance commits. Update only this run: no second User lock/FK insert.
        if run.selection.get("random_mode") == "recommended":
            run.recommendation_delivered_at = datetime.now(UTC)
        run.candidate = candidate.model_dump()
        run.scenario_hash = fingerprint
        run.status = "stopped" if run.stop_requested else "completed"
        run.code, run.message = "ready", "已核对案例已保留；教学质量未验收"
        session.add(run)
        session.commit()
        return True


def allow_correction(run_id: uuid.UUID) -> bool:
    with Session(engine) as session:
        run = session.exec(
            select(TrainingRun).where(TrainingRun.id == run_id).with_for_update()
        ).one()
        if run.stop_requested or run.generation >= 1:
            return False
        run.generation += 1
        run.generation_attempts = 0
        session.add(run)
        session.commit()
        return True


async def watch_stop(run_id: uuid.UUID) -> None:
    while not (await asyncio.to_thread(read_run, run_id)).stop_requested:
        await asyncio.sleep(0.2)


async def process(run_id: uuid.UUID) -> None:
    run = await asyncio.to_thread(read_run, run_id)
    if run.status in TERMINAL or run.stop_requested:
        return
    if (
        run.selection.get("entry") in {"free_topic", "jd", "project"}
        and run.launch_mode != "independent"
    ):
        from app.training.topic_generation import process as process_topic

        await process_topic(run_id)
        return
    if run.launch_mode == "independent":
        from app.training.independent_worker import process as process_independent

        await process_independent(run_id)
        return
    if run.selection.get("catalog_version", CATALOG.version) != CATALOG.version:
        await asyncio.to_thread(
            finish,
            run_id,
            "catalog_changed",
            "能力目录版本已变化，请主动启动新任务；旧任务不改写目标",
        )
        return
    attempt: TrainingAttempt | None = None
    # Reconcile a crash between recording an outcome and choosing its next step.
    # Known malformed/permanent outcomes must not be retried as unknown requests.
    previous = await asyncio.to_thread(last_attempt, run_id)
    if (
        previous
        and previous.code in {"invalid_candidate", "invalid_response"}
        and previous.generation == run.generation
    ):
        if not await asyncio.to_thread(allow_correction, run_id):
            await asyncio.to_thread(
                finish,
                run_id,
                previous.code,
                "候选未通过核对，纠错预算已耗尽；可主动更换方向",
            )
            return
        run = await asyncio.to_thread(read_run, run_id)
    if previous and previous.code not in {
        "unknown",
        "ok",
        "invalid_candidate",
        "invalid_response",
        "connection",
        "timeout",
        "rate_limited",
        "temporary_service",
        "dns",
    }:
        await asyncio.to_thread(
            finish,
            run_id,
            previous.code,
            "上次调用已确定失败，不能因重启自动重试；请核对配置或更换方向",
        )
        return
    try:
        if not run.sources:
            sources = await acquire_source(
                EvidenceKey.model_validate(run.target).capability_id
            )
            await asyncio.to_thread(save_sources, run_id, sources)
        while True:
            run = await asyncio.to_thread(read_run, run_id)
            if run.stop_requested:
                await asyncio.to_thread(
                    finish, run_id, "stopped", "已停止；在途费用请查看供应商账单"
                )
                return
            if run.attempts >= 6 or run.generation_attempts >= 3:
                await asyncio.to_thread(
                    finish,
                    run_id,
                    "budget_exhausted",
                    "本步骤尝试预算已耗尽；未知请求可能计费，可主动更换方向",
                )
                return
            async with call_credential(run.user_id, run.config_version) as (
                config,
                secret,
            ):
                attempt = await asyncio.to_thread(begin_attempt, run_id)
                if attempt is None:
                    return
                raw, counts = await generate(
                    config.service_url,
                    config.model_id,
                    secret.get_secret_value(),
                    EvidenceKey.model_validate(run.target),
                    [Source.model_validate(s) for s in run.sources],
                    run.generation > 0,
                )
                await asyncio.to_thread(record_attempt, attempt.id, "ok", counts)
                try:
                    acceptance = asyncio.create_task(
                        asyncio.to_thread(
                            accept_candidate, run_id, raw, secret.get_secret_value()
                        )
                    )
                    cancelled = False
                    # Cancelling an await cannot stop its synchronous DB thread.
                    # Keep the User permission lock until that thread finishes so
                    # the next selection sees every legally retained publication.
                    while not acceptance.done():
                        try:
                            await asyncio.shield(acceptance)
                        except asyncio.CancelledError:
                            cancelled = True
                        except Exception:
                            break
                    if cancelled:
                        acceptance.exception()  # consume errors; preserve cancellation
                        raise asyncio.CancelledError
                    acceptance.result()
                    return
                except ValueError:
                    await asyncio.to_thread(
                        record_attempt, attempt.id, "invalid_candidate", counts
                    )
            if not await asyncio.to_thread(allow_correction, run_id):
                await asyncio.to_thread(
                    finish,
                    run_id,
                    "invalid_candidate",
                    "候选字段、引用或证据未通过核对，未交付；可更换方向",
                )
                return
    except ProbeError as error:
        if attempt is None:
            # Source reads do not consume the model budget; never retry them through it.
            await asyncio.to_thread(finish, run_id, error.code, error.message)
            return
        if attempt:
            await asyncio.to_thread(
                record_attempt, attempt.id, error.code, error.counts
            )
        run = await asyncio.to_thread(read_run, run_id)
        if error.code == "invalid_response" and await asyncio.to_thread(
            allow_correction, run_id
        ):
            await process(run_id)
        elif (
            error.retry
            and run.generation_attempts < 3
            and run.attempts < 6
            and not run.stop_requested
        ):
            await asyncio.sleep(BACKOFF_SECONDS[max(0, run.generation_attempts - 1)])
            await process(run_id)
        else:
            await asyncio.to_thread(finish, run_id, error.code, error.message)
    except HTTPException:
        await asyncio.to_thread(
            finish,
            run_id,
            "configuration_revoked",
            "配置已变更、删除或账号不可用；旧任务不再调用，请主动使用新配置启动",
        )
    except asyncio.CancelledError as error:
        if attempt and isinstance(error, CancelledCall):
            await asyncio.to_thread(
                record_attempt, attempt.id, "cancelled", error.counts
            )
        # Received tokens already recorded above survive; interrupted attempts remain unknown.
        await asyncio.to_thread(
            finish, run_id, "cancelled", "已尝试中断，未确认请求结果与用量保持未知"
        )
        raise


@queue.task(name="training.generate")
async def generate_training(run_id: str) -> None:
    identity = uuid.UUID(run_id)
    work = asyncio.create_task(process(identity))
    stop = asyncio.create_task(watch_stop(identity))
    try:
        done, _ = await asyncio.wait((work, stop), return_when=asyncio.FIRST_COMPLETED)
        if stop in done and not work.done():
            work.cancel()
        await asyncio.shield(work)
    finally:
        stop.cancel()
        if not work.done() and not work.cancelling():
            work.cancel()
        await asyncio.gather(work, stop, return_exceptions=True)


@queue.periodic(cron="* * * * *")
@queue.task(name="training.recover", queueing_lock="training-recovery")
async def recover(timestamp: int = 0) -> None:
    del timestamp

    await asyncio.to_thread(recover_reviews)
    await asyncio.to_thread(reconcile_topics)
    await asyncio.to_thread(reconcile_stops)
    await asyncio.to_thread(reconcile_failed_submissions)
    await asyncio.to_thread(reconcile_failed_projects)
    await asyncio.to_thread(reconcile_failed_evaluations)
    await asyncio.to_thread(reconcile_concepts)
    for task_name in (
        "topic.analyze",
        "training.generate",
        "training.check_submission",
        "project.analyze",
        "training.evaluate",
        "training.review",
        "training.concept",
    ):
        for job in await queue.job_manager.get_stalled_jobs(task_name=task_name):
            await queue.job_manager.retry_job(job)


async def main() -> None:
    async with queue.open_async():
        await recover()
        await queue.run_worker_async()


if __name__ == "__main__":
    asyncio.run(main())
