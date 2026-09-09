import asyncio
import json
import uuid
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, col, select

from app.core.db import engine
from app.model_config.connection import CancelledCall, ProbeError
from app.model_config.output import check_output
from app.model_config.service import current_for_result, lock_owner
from app.training.gate import call_credential
from app.training.queue import queue
from app.training.topic_analysis import Inspection, analyze
from app.training.topic_models import TopicAttempt, TopicJob
from app.training.topic_rules import Analysis, propose
from app.training.topic_service import compare, owned, save_version, version

TERMINAL = {"completed", "failed", "stopped"}


def read(identity: uuid.UUID) -> TopicJob:
    with Session(engine) as session:
        item = session.get(TopicJob, identity)
        assert item
        session.expunge(item)
        return item


def stage_exit(session: Session, item: TopicJob) -> str | None:
    attempts = session.exec(
        select(TopicAttempt)
        .where(TopicAttempt.run_id == item.id, TopicAttempt.stage == item.stage)
        .order_by(col(TopicAttempt.number))
    ).all()
    malformed = {"invalid_analysis", "invalid_response"}
    if sum(a.code in malformed for a in attempts) >= 2:
        return "invalid_analysis"
    retryable = {
        "ok",
        "unknown",
        "cancelled",
        "connection",
        "timeout",
        "rate_limited",
        "temporary_service",
        "dns",
    } | malformed
    if attempts and attempts[-1].code not in retryable:
        return attempts[-1].code
    return "budget_exhausted" if len(attempts) >= 3 else None


def stage_exhausted(session: Session, item: TopicJob) -> bool:
    return stage_exit(session, item) is not None


def recorded_exit(item: TopicJob) -> str | None:
    with Session(engine) as session:
        return stage_exit(session, item)


def claim(identity: uuid.UUID, job_id: int | None) -> uuid.UUID | None:
    with Session(engine) as session:
        item = session.exec(
            select(TopicJob).where(TopicJob.id == identity).with_for_update()
        ).one()
        if (
            stage_exhausted(session, item)
            or item.queue_job_id != job_id
            or item.status in TERMINAL
            or item.stop_requested
            or item.attempts >= min(item.attempt_limit, 6)
        ):
            return None
        item.attempts += 1
        item.status = "running"
        attempt = TopicAttempt(run_id=item.id, number=item.attempts, stage=item.stage)
        session.add_all([item, attempt])
        session.commit()
        return attempt.id


def record(identity: uuid.UUID, code: str, counts: dict[str, int | None]) -> None:
    with Session(engine) as session:
        attempt = session.get(TopicAttempt, identity)
        assert attempt
        attempt.code = code
        for key, value in counts.items():
            setattr(attempt, key, value)
        session.add(attempt)
        session.commit()


def finish(
    identity: uuid.UUID,
    code: str,
    message: str,
    job_id: int | None = None,
    *,
    require_stop: bool = False,
) -> None:
    with Session(engine) as session:
        item = session.exec(
            select(TopicJob).where(TopicJob.id == identity).with_for_update()
        ).one()
        if (
            (require_stop and not item.stop_requested)
            or item.status in TERMINAL
            or (job_id is not None and item.queue_job_id != job_id)
        ):
            return
        item.status = (
            "stopped" if item.stop_requested or code == "stopped" else "failed"
        )
        item.code, item.message = code, message
        session.add(item)
        session.commit()


def context(item: TopicJob) -> dict[str, Any] | None:
    from app.project.training_models import ProjectInput
    from app.project.training_service import analysis_context, is_project
    from app.training.jd_service import is_jd

    with Session(engine) as session:
        if is_project(session, item.topic_id):
            source = session.get(ProjectInput, item.id)
            assert source
            return analysis_context(source)
        if is_jd(session, item.topic_id):
            return (
                None  # JD analysis needs current text, not previous learning history.
            )
        topic = owned(session, item.topic_id, item.user_id)
        previous = version(session, topic, item.expected_version)
        return (
            {
                "input_text": previous.input_text,
                "kind": previous.kind,
                "nodes": [
                    node.model_dump(mode="json", exclude={"id"})
                    for node in previous.nodes
                ],
            }
            if previous
            else None
        )


def accept(identity: uuid.UUID, raw: str, job_id: int | None) -> bool:
    with Session(engine) as session:
        initial = session.get(TopicJob, identity)
        assert initial
        lock_owner(session, initial.user_id)
        item = session.exec(
            select(TopicJob)
            .where(TopicJob.id == identity)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one()
        if (
            item.queue_job_id != job_id
            or item.stop_requested
            or item.status in TERMINAL
        ):
            return False
        current_for_result(session, item.user_id, item.config_version)
        topic = owned(session, item.topic_id, item.user_id)
        compare(topic, item.expected_version)
        from app.project.training_service import accept as accept_project
        from app.project.training_service import is_project
        from app.training.jd_service import accept as accept_jd
        from app.training.jd_service import is_jd

        if is_project(session, item.topic_id):
            accept_project(session, topic, item, raw)
        elif is_jd(session, item.topic_id):
            accept_jd(session, topic, item, raw)
        elif item.stage == "analyze":
            result = Analysis.model_validate_json(raw)
            # Validate real catalog keys before sending a candidate for inspection.
            propose(
                item.input_text,
                result,
                previous=version(session, topic, item.expected_version),
                expected_version=item.expected_version,
                expand=item.expand,
            )
            item.candidate = result.model_dump(mode="json")
            item.stage = "inspect"
        else:
            inspection = Inspection.model_validate_json(raw)
            if not inspection.accepted or not inspection.explanation.strip():
                raise ValueError("analysis failed content inspection")
            candidate = propose(
                item.input_text,
                Analysis.model_validate(item.candidate),
                previous=version(session, topic, item.expected_version),
                expected_version=item.expected_version,
                expand=item.expand,
            )
            save_version(session, topic, candidate)
            item.result_id = candidate.id
            item.status, item.code, item.message = (
                "completed",
                "ok",
                "主题理解已核对；请编辑并确认，尚未生成题目",
            )
        session.add(item)
        session.commit()
        return True


async def process(identity: uuid.UUID) -> None:
    job_id = (await asyncio.to_thread(read, identity)).queue_job_id

    def finish_current(identity: uuid.UUID, code: str, message: str) -> None:
        finish(identity, code, message, job_id)

    async def watch_stop() -> None:
        while True:
            if (await asyncio.to_thread(read, identity)).stop_requested:
                assert caller
                caller.cancel()
                return
            await asyncio.sleep(0.1)

    caller = asyncio.current_task()
    watcher = asyncio.create_task(watch_stop())
    attempt = None
    try:
        while True:
            item = await asyncio.to_thread(read, identity)
            if (
                item.queue_job_id != job_id
                or item.status in TERMINAL
                or item.stop_requested
            ):
                return
            if item.attempts >= min(item.attempt_limit, 6):
                await asyncio.to_thread(
                    finish_current,
                    identity,
                    "budget_exhausted",
                    "本次预算已用完；可主动重试剩余总预算，不自动生成题目",
                )
                return
            known = await asyncio.to_thread(recorded_exit, item)
            if known:
                await asyncio.to_thread(
                    finish_current,
                    identity,
                    known,
                    "沿用已记录的失败结论；原输入与用量保留，未再次调用模型",
                )
                return
            previous = await asyncio.to_thread(context, item)
            async with call_credential(item.user_id, item.config_version) as (
                config,
                secret,
            ):
                check_output(
                    json.dumps(
                        {
                            "input": item.input_text,
                            "previous": previous,
                            "candidate": item.candidate,
                        },
                        ensure_ascii=False,
                    ),
                    secret.get_secret_value(),
                )
                attempt = await asyncio.to_thread(claim, identity, job_id)
                if attempt is None:
                    await asyncio.to_thread(
                        finish_current,
                        identity,
                        "budget_exhausted",
                        "本阶段尝试或一次纠错已耗尽，原输入保留",
                    )
                    return
                from app.training.jd_models import JDDocument

                def jd_job(identity: uuid.UUID) -> bool:
                    with Session(engine) as session:
                        return session.get(JDDocument, identity) is not None

                if previous is not None and "confirmed_modules" in previous:
                    from app.project.training_analysis import analyze as analyze_project

                    raw, counts = await analyze_project(
                        config.service_url,
                        config.model_id,
                        secret.get_secret_value(),
                        previous,
                        item.candidate if item.stage == "inspect" else None,
                    )
                elif await asyncio.to_thread(jd_job, item.id):
                    from app.training.jd_analysis import analyze as analyze_jd

                    raw, counts = await analyze_jd(
                        config.service_url,
                        config.model_id,
                        secret.get_secret_value(),
                        item.input_text,
                        item.candidate if item.stage == "inspect" else None,
                    )
                else:
                    raw, counts = await analyze(
                        config.service_url,
                        config.model_id,
                        secret.get_secret_value(),
                        item.input_text,
                        previous,
                        item.candidate if item.stage == "inspect" else None,
                    )
                await asyncio.to_thread(record, attempt, "unknown", counts)
            if not await asyncio.to_thread(accept, identity, raw, job_id):
                return
            await asyncio.to_thread(record, attempt, "ok", counts)
            attempt = None
    except ProbeError as error:
        if attempt:
            await asyncio.to_thread(record, attempt, error.code, error.counts)
        await asyncio.to_thread(
            finish_current,
            identity,
            error.code,
            "主题分析未完成；保留输入，可主动重试剩余预算",
        )
    except asyncio.CancelledError as error:
        if attempt and isinstance(error, CancelledCall):
            await asyncio.to_thread(record, attempt, "cancelled", error.counts)
        await asyncio.to_thread(
            finish_current,
            identity,
            "stopped",
            "本次分析已中止；已核对历史保留，在途调用仍可能计费",
        )
        raise
    except ValueError, HTTPException:
        if attempt:
            await asyncio.to_thread(record, attempt, "invalid_analysis", {})
        await asyncio.to_thread(
            finish_current,
            identity,
            "invalid_analysis",
            "候选未通过内容或版本核对；输入与旧路线保留，请读取后主动重试或改写",
        )
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)


@queue.task(name="topic.analyze")
async def analyze_topic(topic_job_id: str) -> None:
    identity = uuid.UUID(topic_job_id)
    captured_job = (await asyncio.to_thread(read, identity)).queue_job_id
    try:
        await process(identity)
    except asyncio.CancelledError:
        raise
    except Exception:
        try:
            await asyncio.to_thread(
                finish,
                identity,
                "internal_failure",
                "主题分析暂未完成，请读取实际状态后主动恢复",
                captured_job,
            )
        except Exception:
            raise RuntimeError(
                "topic recovery required; no request details logged"
            ) from None


def reconcile_topics() -> None:
    with Session(engine) as session:
        items = session.exec(
            select(TopicJob).where(
                col(TopicJob.status).in_(["queued", "running", "stopping"])
            )
        ).all()
        for item in items:
            if item.stop_requested:
                finish(
                    item.id,
                    "stopped",
                    "已停止，旧路线保留",
                    item.queue_job_id,
                    require_stop=True,
                )
