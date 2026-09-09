"""Commit revocation before waiting for in-flight User locks; never revive it."""

import uuid

from fastapi import HTTPException
from sqlmodel import Session, col, select

from app.core.db import engine
from app.model_config.models import ModelConfig
from app.project.models import ProjectRun
from app.training.concept_models import ConceptHelp
from app.training.evaluation_models import Evaluation
from app.training.models import TrainingRun
from app.training.submission_models import Submission


def request_revocation(user_id: uuid.UUID, expected_version: uuid.UUID) -> None:
    # No User/task lock here. In-flight work holds User, but can observe this commit.
    with Session(engine) as session:
        config = session.exec(
            select(ModelConfig)
            .where(ModelConfig.user_id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one_or_none()
        if not config or config.version != expected_version:
            raise HTTPException(409, "配置已变更，请刷新后重新确认；未撤销新版本")
        config.revoked = True
        session.add(config)
        session.commit()


def stop_old_tasks(session: Session, user_id: uuid.UUID, version: uuid.UUID) -> None:
    """Caller holds User. Lock task rows before the final config write.

    Existing worker stop watchers cancel work; the common credential gate also
    observes revoked/version without User. Queue redelivery cannot revive these rows.
    Completed artifacts and attempt rows are deliberately not rewritten.
    """
    run_ids = select(TrainingRun.id).where(TrainingRun.user_id == user_id)
    for model, owner in (
        (TrainingRun, TrainingRun.user_id == user_id),
        (ProjectRun, ProjectRun.user_id == user_id),
        (Submission, col(Submission.run_id).in_(run_ids)),
        (Evaluation, col(Evaluation.run_id).in_(run_ids)),
        (ConceptHelp, col(ConceptHelp.run_id).in_(run_ids)),
    ):
        items = session.exec(
            select(model)
            .where(
                owner,
                model.config_version == version,
                col(model.status).in_(["queued", "running", "checking", "stopping"]),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
        for item in items:
            item.stop_requested = True
            item.status = "stopped"
            item.code = "configuration_revoked"
            item.message = "旧配置后续调用已终止；已核对成果保留，在途请求尝试取消，仍可能收费。使用新配置须主动启动。"
            session.add(item)
