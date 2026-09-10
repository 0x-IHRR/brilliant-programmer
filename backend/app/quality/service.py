"""Owner-serialized admission; callers hold User, never acquire it across model IO."""

import json
import uuid

from fastapi import HTTPException
from sqlmodel import Session, col, select

from app.quality.models import QualityDisposition, QualityReport
from app.quality.rules import Binding, QualityStatus, Report, applicability
from app.training.evaluation_models import Evaluation
from app.training.models import TrainingRun
from app.training.schema import Source


def same_binding(session: Session, row: QualityReport, binding: Binding) -> bool:
    if row.report:
        return Report.model_validate_json(json.dumps(row.report)).binding == binding
    from app.deletion.models import ErasedObject
    from app.deletion.quality import binding_digest

    marker = session.get(ErasedObject, (binding.user_id, "quality", row.id))
    return bool(marker and marker.binding_digest == binding_digest(binding))


def latest(session: Session, binding: Binding) -> QualityReport | None:
    # Prefer the exact configuration/rule. Other configurations only explain why
    # a previously seen report does not apply; they cannot mask an exact failure.
    rows = session.exec(
        select(QualityReport)
        .where(QualityReport.user_id == binding.user_id)
        .order_by(col(QualityReport.sequence).desc())
    ).all()
    for row in rows:
        if same_binding(session, row, binding):
            return row
    return rows[0] if rows else None


def status(
    session: Session, binding: Binding, sources: list[Source] | None
) -> tuple[QualityStatus, QualityReport | None]:

    row = latest(session, binding)
    report = (
        Report.model_validate_json(json.dumps(row.report))
        if row and row.report
        else None
    )
    return applicability(report, binding, sources), row


def require_start(
    session: Session, binding: Binding, sources: list[Source] | None
) -> None:
    state, _ = status(session, binding, sources)
    if state == "failed":
        raise HTTPException(
            409,
            "该配置已有未达标评分依据，暂不开放新独立检验或 Boss；可继续普通练习与复盘。来源尚未取得时不能确认新来源适用性，修复后需受信任复测依据",
        )


def freeze(
    session: Session,
    run: TrainingRun,
    evaluation: Evaluation,
    *,
    phase: str = "original",
    binding: Binding | None = None,
) -> QualityDisposition:
    existing = session.get(QualityDisposition, (run.id, phase))
    if existing:
        return existing
    actual = binding or Binding(
        user_id=run.user_id,
        config_version=evaluation.config_version,
        destination=evaluation.destination,
        model_id=evaluation.model_id,
        evaluation_rule=evaluation.rule_version,
    )
    state, report = status(
        session, actual, [Source.model_validate(s) for s in evaluation.sources]
    )
    item = QualityDisposition(
        run_id=run.id,
        phase=phase,
        report_id=report.id if report else None,
        status=state,
        binding=actual.model_dump(mode="json"),
    )
    session.add(item)
    session.flush()
    return item


def permitted(session: Session, run_id: uuid.UUID, phase: str = "original") -> bool:
    # Legacy records are unknown, not retrospectively failed. Migration pins this
    # fact for existing observations before any report can be imported.
    item = session.get(QualityDisposition, (run_id, phase))
    return item is None or item.status != "failed"
