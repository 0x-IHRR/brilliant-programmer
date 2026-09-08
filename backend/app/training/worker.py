import asyncio
import uuid

from fastapi import HTTPException
from sqlmodel import Session, select

from app.capabilities.catalog import EvidenceKey
from app.core.db import engine
from app.model_config.connection import BACKOFF_SECONDS, ProbeError
from app.training.gate import call_credential
from app.training.generation import generate
from app.training.models import TrainingAttempt, TrainingRun
from app.training.queue import queue
from app.training.schema import Source, scenario_fingerprint, validate_candidate
from app.training.sources import acquire_source

TERMINAL = {"completed", "failed", "stopped"}


def read_run(run_id: uuid.UUID) -> TrainingRun:
    with Session(engine) as session:
        run = session.get(TrainingRun, run_id)
        if run is None:
            raise ValueError("missing training")
        return run


def finish(run_id: uuid.UUID, code: str, message: str) -> None:
    with Session(engine) as session:
        run = session.exec(select(TrainingRun).where(TrainingRun.id == run_id).with_for_update()).one()
        if run.candidate:
            run.status = "stopped" if run.stop_requested else "completed"
        else:
            run.status = "stopped" if run.stop_requested else "failed"
        run.code, run.message = code, message
        session.add(run)
        session.commit()


def begin_attempt(run_id: uuid.UUID) -> TrainingAttempt | None:
    with Session(engine) as session:
        run = session.exec(select(TrainingRun).where(TrainingRun.id == run_id).with_for_update()).one()
        if run.stop_requested or run.status in TERMINAL or run.attempts >= 6 or run.generation_attempts >= 3:
            return None
        run.status, run.code, run.message = "running", "generating", "模型正在生成并核对候选"
        run.attempts += 1
        run.generation_attempts += 1
        attempt = TrainingAttempt(run_id=run.id, number=run.attempts, generation=run.generation)
        session.add(run)
        session.add(attempt)
        session.commit()
        session.refresh(attempt)
        return attempt


def record_attempt(attempt_id: uuid.UUID, code: str, counts: dict[str, int | None]) -> None:
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
        run = session.exec(select(TrainingRun).where(TrainingRun.id == run_id).with_for_update()).one()
        run.sources = [source.model_dump() for source in sources]
        session.add(run)
        session.commit()


def accept_candidate(run_id: uuid.UUID, raw: str, key: str) -> bool:
    with Session(engine) as session:
        run = session.exec(select(TrainingRun).where(TrainingRun.id == run_id).with_for_update()).one()
        candidate = validate_candidate(raw, EvidenceKey.model_validate(run.target), [Source.model_validate(s) for s in run.sources], key)
        fingerprint = scenario_fingerprint(candidate)
        previous = session.exec(select(TrainingRun.id).where(TrainingRun.user_id == run.user_id, TrainingRun.scenario_hash == fingerprint, TrainingRun.id != run.id)).first()
        if previous:
            raise ValueError("repeated scenario")
        run.candidate = candidate.model_dump()
        run.scenario_hash = fingerprint
        run.status = "stopped" if run.stop_requested else "completed"
        run.code, run.message = "ready", "已核对案例已保留；教学质量未验收"
        session.add(run)
        session.commit()
        return True


def allow_correction(run_id: uuid.UUID) -> bool:
    with Session(engine) as session:
        run = session.exec(select(TrainingRun).where(TrainingRun.id == run_id).with_for_update()).one()
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
    attempt: TrainingAttempt | None = None
    try:
        if not run.sources:
            sources = await acquire_source(EvidenceKey.model_validate(run.target).capability_id)
            await asyncio.to_thread(save_sources, run_id, sources)
        while True:
            run = await asyncio.to_thread(read_run, run_id)
            if run.stop_requested:
                await asyncio.to_thread(finish, run_id, "stopped", "已停止；在途费用请查看供应商账单")
                return
            if run.attempts >= 6 or run.generation_attempts >= 3:
                await asyncio.to_thread(finish, run_id, "budget_exhausted", "本步骤尝试预算已耗尽；未知请求可能计费，可主动更换方向")
                return
            async with call_credential(run.user_id, run.config_version) as (config, secret):
                attempt = await asyncio.to_thread(begin_attempt, run_id)
                if attempt is None:
                    return
                raw, counts = await generate(config.service_url, config.model_id, secret.get_secret_value(), EvidenceKey.model_validate(run.target), [Source.model_validate(s) for s in run.sources], run.generation > 0)
                await asyncio.to_thread(record_attempt, attempt.id, "ok", counts)
                try:
                    await asyncio.to_thread(accept_candidate, run_id, raw, secret.get_secret_value())
                    return
                except ValueError:
                    await asyncio.to_thread(record_attempt, attempt.id, "invalid_candidate", counts)
            if not await asyncio.to_thread(allow_correction, run_id):
                await asyncio.to_thread(finish, run_id, "invalid_candidate", "候选字段、引用或证据未通过核对，未交付；可更换方向")
                return
    except ProbeError as error:
        if attempt:
            await asyncio.to_thread(record_attempt, attempt.id, error.code, error.counts)
        run = await asyncio.to_thread(read_run, run_id)
        if error.code == "invalid_response" and await asyncio.to_thread(allow_correction, run_id):
            await process(run_id)
        elif error.retry and run.generation_attempts < 3 and run.attempts < 6 and not run.stop_requested:
            await asyncio.sleep(BACKOFF_SECONDS[max(0, run.generation_attempts - 1)])
            await process(run_id)
        else:
            await asyncio.to_thread(finish, run_id, error.code, error.message)
    except HTTPException:
        await asyncio.to_thread(finish, run_id, "configuration_revoked", "配置已变更、删除或账号不可用；旧任务不再调用，请主动使用新配置启动")
    except asyncio.CancelledError:
        # Received tokens already recorded above survive; interrupted attempts remain unknown.
        await asyncio.to_thread(finish, run_id, "cancelled", "已尝试中断，未确认请求结果与用量保持未知")
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
        await work
    finally:
        stop.cancel()
        if not work.done():
            work.cancel()
        await asyncio.gather(work, stop, return_exceptions=True)


@queue.periodic(cron="* * * * *")
@queue.task(name="training.recover", queueing_lock="training-recovery")
async def recover(timestamp: int = 0) -> None:
    del timestamp
    for job in await queue.job_manager.get_stalled_jobs(task_name="training.generate"):
        await queue.job_manager.retry_job(job)


async def main() -> None:
    async with queue.open_async():
        await recover()
        await queue.run_worker_async()


if __name__ == "__main__":
    asyncio.run(main())
