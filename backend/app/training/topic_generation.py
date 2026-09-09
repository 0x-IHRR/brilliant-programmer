"""Private generated candidate survives inspection retries within the six-call budget."""

import asyncio
import json
import uuid

from fastapi import HTTPException
from sqlmodel import Session, select

from app.capabilities.catalog import CATALOG, EvidenceKey
from app.core.db import engine
from app.model_config.connection import BACKOFF_SECONDS, CancelledCall, ProbeError
from app.model_config.output import check_output
from app.model_config.service import current_for_result
from app.training.gate import call_credential
from app.training.generation import generate
from app.training.models import TrainingRun
from app.training.schema import Source, validate_candidate
from app.training.sources import acquire_source
from app.training.topic_analysis import Inspection, inspect_case
from app.training.topic_models import TopicCase


def private(identity: uuid.UUID) -> TopicCase | None:
    with Session(engine) as session:
        item = session.get(TopicCase, identity)
        if item:
            session.expunge(item)
        return item


def checkpoint(identity: uuid.UUID, raw: str, key: str, job_id: int | None) -> bool:
    with Session(engine) as session:
        run = session.exec(
            select(TrainingRun).where(TrainingRun.id == identity).with_for_update()
        ).one()
        if (
            run.queue_job_id != job_id
            or run.stop_requested
            or run.status in {"completed", "failed", "stopped"}
        ):
            return False
        current_for_result(session, run.user_id, run.config_version)
        candidate = validate_candidate(
            raw,
            EvidenceKey.model_validate(run.target),
            [Source.model_validate(s) for s in run.sources],
            key,
        )
        if not session.get(TopicCase, identity):
            session.add(
                TopicCase(run_id=identity, candidate=candidate.model_dump(mode="json"))
            )
        run.generation = 1
        run.generation_attempts = 0
        session.add(run)
        session.commit()
        return True


async def process(identity: uuid.UUID) -> None:
    from app.training.independent_worker import recorded_exit
    from app.training.worker import (
        accept_candidate,
        begin_attempt,
        finish,
        read_run,
        record_attempt,
        save_sources,
    )

    initial = await asyncio.to_thread(read_run, identity)
    job_id = initial.queue_job_id

    async def stop(code: str, message: str) -> None:
        await asyncio.to_thread(finish, identity, code, message, job_id)

    attempt = None
    while True:
        run = await asyncio.to_thread(read_run, identity)
        if (
            run.queue_job_id != job_id
            or run.stop_requested
            or run.status in {"completed", "failed", "stopped"}
        ):
            return
        if run.selection.get("catalog_version") != CATALOG.version:
            await stop("catalog_changed", "目录已变化，原目标不改写；请重新确认路线")
            return
        if code := await asyncio.to_thread(recorded_exit, run):
            await stop(code, "已记录失败或一次纠错已耗尽，未发布题目；原目标保留")
            return
        if run.attempts >= 6 or run.generation_attempts >= 3:
            await stop(
                "budget_exhausted",
                "本阶段预算已耗尽，目标与未交付记录保留；可主动调整后新建",
            )
            return
        attempt = None
        counts: dict[str, int | None] = {}
        try:
            if not run.sources:
                sources = await acquire_source(
                    EvidenceKey.model_validate(run.target).capability_id
                )
                await asyncio.to_thread(save_sources, identity, sources)
                run = await asyncio.to_thread(read_run, identity)
            async with call_credential(run.user_id, run.config_version) as (
                config,
                secret,
            ):
                check_output(
                    json.dumps(
                        {
                            "goal": run.selection["goal"],
                            "focus": run.selection["focus"],
                            "sources": run.sources,
                        },
                        ensure_ascii=False,
                    ),
                    secret.get_secret_value(),
                )
                attempt = await asyncio.to_thread(begin_attempt, identity, job_id)
                if attempt is None:
                    return
                goal = {"goal": run.selection["goal"], "focus": run.selection["focus"]}
                key = secret.get_secret_value()
                if run.generation == 0:
                    raw, counts = await generate(
                        config.service_url,
                        config.model_id,
                        key,
                        EvidenceKey.model_validate(run.target),
                        [Source.model_validate(s) for s in run.sources],
                        run.generation_attempts > 0,
                        topic_goal=goal,
                    )
                    await asyncio.to_thread(
                        record_attempt, attempt.id, "unknown", counts
                    )
                    if not await asyncio.to_thread(
                        checkpoint, identity, raw, key, job_id
                    ):
                        return
                else:
                    saved = await asyncio.to_thread(private, identity)
                    if not saved:
                        await stop(
                            "internal_failure", "私有候选无法恢复，未重新生成或交付"
                        )
                        return
                    raw = json.dumps(saved.candidate, ensure_ascii=False)
                    inspected, counts = await inspect_case(
                        config.service_url, config.model_id, key, goal, raw, run.sources
                    )
                    await asyncio.to_thread(
                        record_attempt, attempt.id, "unknown", counts
                    )
                    verdict = Inspection.model_validate_json(inspected)
                    if not verdict.accepted or not verdict.explanation.strip():
                        await asyncio.to_thread(
                            record_attempt, attempt.id, "unsupported_topic", counts
                        )
                        await stop(
                            "unsupported_topic",
                            "实际案例或来源不能支持确认目标，未换成默认题；请调整目标或主动重试新题",
                        )
                        return
                    acceptance = asyncio.create_task(
                        asyncio.to_thread(accept_candidate, identity, raw, key)
                    )
                    cancelled = False
                    while not acceptance.done():
                        try:
                            await asyncio.shield(acceptance)
                        except asyncio.CancelledError:
                            cancelled = True
                        except Exception:
                            break
                    if cancelled:
                        acceptance.exception()
                        raise asyncio.CancelledError
                    acceptance.result()
                await asyncio.to_thread(record_attempt, attempt.id, "ok", counts)
                attempt = None
                if run.generation == 1:
                    return
        except ProbeError as error:
            if attempt:
                await asyncio.to_thread(
                    record_attempt, attempt.id, error.code, error.counts
                )
            if not attempt or not (error.retry or error.code == "invalid_response"):
                await stop(error.code, error.message)
                return
            await asyncio.sleep(
                BACKOFF_SECONDS[min(1, max(0, run.generation_attempts))]
            )
        except ValueError:
            if not attempt:
                await stop("unsafe_input", "输入或来源疑似包含秘密，未发送；请修改目标")
                return
            if attempt:
                await asyncio.to_thread(
                    record_attempt, attempt.id, "invalid_candidate", counts
                )
            # Malformed generation/inspection retries the same stage, never resets budget.
        except HTTPException:
            await stop(
                "configuration_revoked",
                "配置已变化，旧目标保留，不再调用；请确认配置后主动新建",
            )
            return
        except asyncio.CancelledError as error:
            if attempt and isinstance(error, CancelledCall):
                await asyncio.to_thread(
                    record_attempt, attempt.id, "cancelled", error.counts
                )
            await stop(
                "cancelled", "已尝试停止，在途用量未知部分保持未知；旧目标与成果保留"
            )
            raise
        except Exception:
            try:
                await stop(
                    "internal_failure",
                    "生成或核对暂未完成，原目标保留；请读取状态后主动恢复",
                )
            except Exception:
                raise RuntimeError("topic generation storage unavailable") from None
            return
