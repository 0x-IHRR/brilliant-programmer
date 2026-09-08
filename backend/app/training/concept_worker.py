"""Persisted, bounded two-stage concept generation in the existing worker."""

import asyncio
import json
import uuid
from typing import Literal

import procrastinate
from fastapi import HTTPException
from sqlmodel import Session, col, select

from app.core.db import engine
from app.model_config.connection import BACKOFF_SECONDS, CancelledCall, ProbeError
from app.model_config.models import ModelConfig
from app.model_config.service import lock_owner
from app.training.concept import (
    coach_call,
    context_for,
    inspection_context,
    validate_content,
    validate_inspection,
)
from app.training.concept_models import ConceptAttempt, ConceptHelp, HelpDelivery
from app.training.concept_schema import ConceptContent, HelpInput, classify_content
from app.training.events import next_event
from app.training.gate import call_credential
from app.training.models import TrainingRun
from app.training.queue import DSN, queue
from app.training.schema import Candidate, Source
from app.training.submission_worker import RETRYABLE


def read_help(
    identity: uuid.UUID,
) -> tuple[ConceptHelp, TrainingRun, list[ConceptContent]]:
    with Session(engine) as session:
        item = session.get(ConceptHelp, identity)
        if not item:
            raise ValueError("missing concept request")
        run = session.get(TrainingRun, item.run_id)
        assert run
        history = []
        if item.parent_id:
            parent = session.get(ConceptHelp, item.parent_id)
            observed = session.exec(
                select(HelpDelivery.id).where(
                    HelpDelivery.help_id == item.parent_id,
                    HelpDelivery.status == "delivered",
                )
            ).first()
            if (
                not parent
                or parent.run_id != run.id
                or not observed
                or not parent.content
            ):
                raise ValueError("parent help not delivered")
            history.append(ConceptContent.model_validate(parent.content))
        return item, run, history


def claim(identity: uuid.UUID) -> ConceptAttempt | None:
    with Session(engine) as session:
        item = session.exec(
            select(ConceptHelp).where(ConceptHelp.id == identity).with_for_update()
        ).one()
        if item.status != "checking" or item.stop_requested:
            return None
        last = session.exec(
            select(ConceptAttempt)
            .where(ConceptAttempt.help_id == identity)
            .order_by(col(ConceptAttempt.number).desc())
        ).first()
        terminal = (
            last and last.stage == item.stage and last.code not in RETRYABLE | {"ok"}
        )
        if item.attempts >= 6 or item.stage_attempts >= item.attempt_limit or terminal:
            item.status, item.code, item.message = (
                "failed",
                last.code if terminal and last else "budget_exhausted",
                "本次帮助预算已耗尽；输入保留，尚未交付。",
            )
            session.add(item)
            session.commit()
            return None
        item.attempts += 1
        item.stage_attempts += 1
        attempt = ConceptAttempt(
            help_id=identity, number=item.attempts, stage=item.stage
        )
        session.add(item)
        session.add(attempt)
        session.commit()
        session.refresh(attempt)
        return attempt


def record_attempt(
    identity: uuid.UUID, code: str, counts: dict[str, int | None]
) -> None:
    with Session(engine) as session:
        attempt = session.get(ConceptAttempt, identity)
        assert attempt
        attempt.code = code
        for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
            setattr(attempt, name, counts.get(name))
        session.add(attempt)
        session.commit()


def fail(identity: uuid.UUID, code: str, message: str) -> None:
    with Session(engine) as session:
        item = session.exec(
            select(ConceptHelp).where(ConceptHelp.id == identity).with_for_update()
        ).one()
        if item.status != "checking" or item.stop_requested:
            return
        item.status, item.code, item.message = "failed", code, message
        session.add(item)
        session.commit()


def accept(identity: uuid.UUID, raw: str, key: str, stage: str) -> bool:
    with Session(engine) as session:
        item = session.get(ConceptHelp, identity)
        assert item
        run = session.get(TrainingRun, item.run_id)
        assert run
        lock_owner(session, run.user_id)
        # Stop writes its intent under this same row lock. Keep it through the
        # terminal update, in the established owner -> help -> run lock order.
        item = session.exec(
            select(ConceptHelp)
            .where(ConceptHelp.id == identity)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one()
        if item.status != "checking" or item.stop_requested or item.stage != stage:
            return False
        config = session.get(ModelConfig, run.user_id, populate_existing=True)
        if not config or config.version != item.config_version:
            raise HTTPException(409, "configuration revoked")
        if stage == "generate":
            content = validate_content(
                raw,
                HelpInput.model_validate(item.request),
                Candidate.model_validate(run.candidate),
                key,
            )
            item.generated_sequence = next_event(session, run.id)
            item.content = content.model_dump(exclude_none=True)
            item.stage = "inspect"
            item.stage_attempts = 0
            item.attempt_limit = 3
            item.message = "说明已生成，正在检查实际内容；尚未交付"
        else:
            content = ConceptContent.model_validate(item.content)
            review = validate_inspection(raw, content, key)
            item.checked_sequence = next_event(session, run.id)
            item.inspection = review.model_dump()
            item.direction = classify_content(content, review)
            item.status, item.code, item.message = (
                "ready",
                "ready",
                "说明已准备好，交付情况见记录。内容检查为模型推断，非人工核验。",
            )
        session.add(item)
        session.commit()
        return True


async def process_help(identity: uuid.UUID) -> None:
    while True:
        item, run, history = await asyncio.to_thread(read_help, identity)
        if item.status != "checking" or item.stop_requested:
            return
        attempt = None
        counts: dict[str, int | None] = {}
        try:
            async with call_credential(run.user_id, item.config_version) as (
                config,
                secret,
            ):
                case = Candidate.model_validate(run.candidate)
                context = context_for(
                    case,
                    [Source.model_validate(s) for s in run.sources],
                    HelpInput.model_validate(item.request),
                    history,
                )
                stage: Literal["generate", "inspect"] = (
                    "generate" if item.stage == "generate" else "inspect"
                )
                if stage == "inspect":
                    context = inspection_context(
                        context, case, ConceptContent.model_validate(item.content)
                    )
                # Check before claiming a paid dispatch; coach_call checks again at transport.
                from app.model_config.output import check_output

                check_output(
                    json.dumps(context, ensure_ascii=False), secret.get_secret_value()
                )
                attempt = await asyncio.to_thread(claim, identity)
                if attempt is None:
                    return
                raw, counts = await coach_call(
                    config.service_url,
                    config.model_id,
                    secret.get_secret_value(),
                    context,
                    stage,
                )
                await asyncio.to_thread(record_attempt, attempt.id, "unknown", counts)
            if not await asyncio.to_thread(
                accept, identity, raw, secret.get_secret_value(), stage
            ):
                return
            await asyncio.to_thread(record_attempt, attempt.id, "ok", counts)
        except ProbeError as error:
            if attempt:
                await asyncio.to_thread(
                    record_attempt, attempt.id, error.code, error.counts
                )
            current, _, _ = await asyncio.to_thread(read_help, identity)
            if (
                error.retry
                and current.attempts < 6
                and current.stage_attempts < current.attempt_limit
            ):
                remaining = current.attempt_limit - current.stage_attempts
                await asyncio.sleep(BACKOFF_SECONDS[min(1, max(0, 2 - remaining))])
                continue
            await asyncio.to_thread(
                fail, identity, error.code, error.message + " 输入保留，尚未交付。"
            )
            return
        except asyncio.CancelledError as error:
            if attempt and isinstance(error, CancelledCall):
                await asyncio.to_thread(
                    record_attempt, attempt.id, "cancelled", error.counts
                )
            raise
        except HTTPException:
            await asyncio.to_thread(
                fail,
                identity,
                "configuration_revoked",
                "配置已变更；旧帮助不继续调用，输入保留。",
            )
            return
        except ValueError:
            if attempt:
                await asyncio.to_thread(
                    record_attempt, attempt.id, "invalid_response", counts
                )
            await asyncio.to_thread(
                fail,
                identity,
                "invalid_response" if attempt else "input_secret",
                "必要内容无法安全核对，未交付；输入保留，请核对材料或脱敏。",
            )
            return


@queue.task(name="training.concept")
async def generate_help(help_id: str) -> None:
    identity = uuid.UUID(help_id)

    async def watch_stop() -> None:
        while not (await asyncio.to_thread(read_help, identity))[0].stop_requested:
            await asyncio.sleep(0.2)

    work, stop = (
        asyncio.create_task(process_help(identity)),
        asyncio.create_task(watch_stop()),
    )
    try:
        done, _ = await asyncio.wait((work, stop), return_when=asyncio.FIRST_COMPLETED)
        if stop in done and not work.done():
            work.cancel()
        await asyncio.shield(work)
    except Exception:
        try:
            await asyncio.to_thread(
                fail,
                identity,
                "internal_failure",
                "帮助暂时失败，输入保留，可主动重试；尚未交付。",
            )
        except Exception:
            raise RuntimeError("concept storage temporarily unavailable") from None
    finally:
        stop.cancel()
        if not work.done() and not work.cancelling():
            work.cancel()
        await asyncio.gather(work, stop, return_exceptions=True)


def finish_stop(identity: uuid.UUID, job_id: int | None) -> None:
    with procrastinate.App(
        connector=procrastinate.SyncPsycopgConnector(conninfo=DSN)
    ).open() as app:
        if job_id is not None:
            app.job_manager.cancel_job_by_id(job_id, abort=True)
    with Session(engine) as session:
        item = session.get(ConceptHelp, identity)
        assert item
        run = session.get(TrainingRun, item.run_id)
        assert run
        lock_owner(session, run.user_id)
        session.refresh(item)
        if (
            item.status == "stopping"
            and item.stop_requested
            and item.queue_job_id == job_id
        ):
            item.status, item.code, item.message = (
                "stopped",
                "stopped",
                "帮助已停止，输入和已有成果保留；未产生新交付，在途费用不保证撤回。",
            )
            session.add(item)
            session.commit()


def reconcile_concepts() -> None:
    from sqlalchemy import text

    with Session(engine) as session:
        pending = session.exec(
            select(ConceptHelp.id, ConceptHelp.queue_job_id)
            .where(ConceptHelp.status == "stopping")
            .limit(100)
        ).all()
    for identity, job_id in pending:
        finish_stop(identity, job_id)
    with engine.connect() as connection:
        failed = connection.execute(
            text(
                "SELECT h.id FROM concept_help h JOIN procrastinate_jobs j ON j.id=h.queue_job_id WHERE h.status='checking' AND j.status IN ('failed','aborted','cancelled') LIMIT 100"
            )
        ).all()
    for (identity,) in failed:
        fail(
            identity,
            "internal_failure",
            "上次帮助未完成；输入保留，可主动重试，预算不重置。",
        )
