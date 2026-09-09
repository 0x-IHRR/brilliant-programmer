"""Allowlisted report metadata; no rubric, answer, provider output or evidence bytes."""

import json
import uuid
from datetime import datetime

from pydantic import BaseModel
from sqlmodel import Session

from app.quality.rules import Binding, QualityStatus, Report, result


class QualityPublic(BaseModel):
    status: QualityStatus
    report_id: uuid.UUID | None = None
    artifact_sha256: str | None = None
    evaluation_rule: str
    corpus_version: str | None = None
    annotation_version: str | None = None
    checked_at: datetime | None = None
    sample_count: int | None = None
    correct_count: int | None = None
    safety_false_accepts: int | None = None
    source_versions: list[str] = []


def describe(session: Session, binding: Binding) -> QualityPublic:
    from app.quality.service import latest

    row = latest(session, binding)
    if not row:
        return QualityPublic(
            status="unverified", evaluation_rule=binding.evaluation_rule
        )
    report = Report.model_validate_json(json.dumps(row.report))
    return QualityPublic(
        status=result(report) if report.binding == binding else "version_mismatch",
        report_id=row.id,
        artifact_sha256=row.artifact_sha256,
        evaluation_rule=report.binding.evaluation_rule,
        corpus_version=report.corpus_version,
        annotation_version=report.annotation_version,
        checked_at=row.created_at,
        sample_count=len(report.samples),
        correct_count=sum(s.expected == s.observed for s in report.samples),
        safety_false_accepts=sum(
            s.critical_safety and s.expected != "pass" and s.observed == "pass"
            for s in report.samples
        ),
        source_versions=sorted(
            {s.url + " · " + s.version for c in report.cases for s in c.sources}
        ),
    )
