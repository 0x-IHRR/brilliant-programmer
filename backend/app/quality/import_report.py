"""Local operator import. No API role, network, provider or grader is invoked.

The operator reviews the actual artifact and referenced content before invoking
this command with its SHA-256. Hashes prove byte identity, not human correctness.
"""

import argparse
import hashlib
import json
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, col, select

from app.core.db import engine
from app.model_config.output import check_output
from app.model_config.service import lock_owner
from app.quality.models import QualityEvidence, QualityReport
from app.quality.rules import Report, result


def load(
    path: Path, expected_sha256: str, evidence: Path
) -> tuple[Report, str, dict[str, bytes]]:
    if path.is_symlink() or path.stat().st_size > 20_000_000:
        raise ValueError("artifact must be a bounded regular local file")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_sha256:
        raise ValueError("artifact differs from the operator-reviewed digest")
    check_output(raw.decode("utf-8"), "")
    report = Report.model_validate_json(raw)
    hashes = (
        {h for c in report.cases for h in (c.case_sha256, c.human_source_check_sha256)}
        | {
            h
            for s in report.samples
            for h in (s.answer_sha256, s.annotation_sha256, s.output_sha256)
        }
        | {s.text_sha256 for c in report.cases for s in c.sources}
    )
    total = 0
    files: dict[str, bytes] = {}
    for expected in hashes:
        file = evidence / expected
        if file.is_symlink() or not file.is_file():
            raise ValueError("missing regular evidence file")
        size = file.stat().st_size
        total += size
        if size > 20_000_000 or total > 200_000_000:
            raise ValueError("evidence exceeds local import bounds")
        content = file.read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError("evidence content differs from report")
        check_output(content.decode("utf-8"), "")
        files[expected] = content
    validate_evidence(report, files)
    return report, digest, files


def validate_evidence(report: Report, files: dict[str, bytes]) -> None:
    from app.training.evaluation_schema import EvaluationInputs, validate_grading
    from app.training.schema import Candidate, Source, validate_candidate
    from app.training.submission_schema import validate_answers

    cases = {}
    for row in report.cases:
        raw = files[row.case_sha256].decode("utf-8")
        candidate = Candidate.model_validate_json(raw)
        if (
            candidate.target.capability_id.split(".")[0],
            candidate.target.difficulty,
        ) != (row.domain_id, row.difficulty):
            raise ValueError("case does not belong to claimed coverage cell")
        sources = [
            Source(
                id=s.id,
                url=s.url,
                version=s.version,
                locator=s.locator,
                text=files[s.text_sha256].decode("utf-8"),
            )
            for s in row.sources
        ]
        candidate = validate_candidate(raw, candidate.target, sources, "")
        check = json.loads(files[row.human_source_check_sha256].decode("utf-8"))
        if (
            check.get("case_sha256") != row.case_sha256
            or check.get("source_checks")
            != [s.model_dump(mode="json") for s in row.sources]
            or not check.get("rationale")
        ):
            raise ValueError(
                "source-check record does not bind actual case and sources"
            )
        cases[row.id] = (candidate, sources)
    for sample in report.samples:
        candidate, sources = cases[sample.case_id]
        inputs = EvaluationInputs.model_validate_json(
            files[sample.answer_sha256].decode("utf-8")
        )
        validate_answers(candidate, inputs.original.answers)
        if inputs.clarification:
            if (
                inputs.clarification.sequence <= inputs.original.sequence
                or not inputs.clarification_used
            ):
                raise ValueError("unfrozen clarification order")
            validate_answers(candidate, inputs.clarification.answers)
        raw = files[sample.output_sha256].decode("utf-8")
        if sample.judgment_id not in {j.id for j in candidate.judgments}:
            raise ValueError("sample references a different judgment")
        try:
            grading = validate_grading(raw, candidate, sources, inputs, "")
        except ValueError:
            if sample.observed != "invalid_output":
                raise ValueError(
                    "reported result differs from invalid actual output"
                ) from None
        else:
            item = next(
                (i for i in grading.items if i.judgment_id == sample.judgment_id), None
            )
            if item is None or item.conclusion != sample.observed:
                raise ValueError("reported result differs from actual grading item")
        annotation = json.loads(files[sample.annotation_sha256].decode("utf-8"))
        expected = {
            "case_id": sample.case_id,
            "answer_sha256": sample.answer_sha256,
            "judgment_id": sample.judgment_id,
            "expected": sample.expected,
            "critical_safety": sample.critical_safety,
        }
        if any(
            annotation.get(k) != v for k, v in expected.items()
        ) or not annotation.get("rationale"):
            raise ValueError("label does not bind the sampled answer and judgment")


def save(
    session: Session, report: Report, digest: str, files: dict[str, bytes] | None = None
) -> QualityReport:
    """Caller commits; receipt identity and predecessor serialize under User."""
    lock_owner(session, report.binding.user_id)
    from app.deletion.models import ErasedObject, ErasedRow
    from app.deletion.quality import lock_hashes
    from app.deletion.scope import references

    markers = session.exec(
        select(ErasedObject).where(ErasedObject.user_id == report.binding.user_id)
    ).all()
    erased_ids = {str(m.object_id) for m in markers}
    erased_ids.update(
        session.exec(
            select(ErasedRow.row_key).where(
                ErasedRow.user_id == report.binding.user_id,
                ErasedRow.table_name == "training_submission",
            )
        ).all()
    )
    if str(report.artifact_id) in erased_ids:
        raise ValueError("deleted report identity cannot be replayed")
    for content in (files or {}).values():
        try:
            parsed = json.loads(content)
        except ValueError:
            continue
        if references(parsed, erased_ids):
            raise ValueError("deleted original identity cannot be reattached")
    lock_hashes(session, set(files or {}))
    existing = session.get(QualityReport, report.artifact_id)
    if existing:
        if (
            existing.artifact_sha256 != digest
            or existing.user_id != report.binding.user_id
        ):
            raise ValueError("artifact identity already used")
        return existing
    rows = session.exec(
        select(QualityReport)
        .where(QualityReport.user_id == report.binding.user_id)
        .order_by(col(QualityReport.sequence).desc())
    ).all()
    from app.quality.service import same_binding

    predecessor = next(
        (r for r in rows if same_binding(session, r, report.binding)), None
    )
    if report.supersedes != (predecessor.id if predecessor else None):
        raise ValueError("retest predecessor changed; review the current artifact")
    for sha256, content in sorted((files or {}).items()):
        if hashlib.sha256(content).hexdigest() != sha256:
            raise ValueError("evidence bytes changed before storage")
        session.execute(
            insert(QualityEvidence)
            .values(sha256=sha256, content=content)
            .on_conflict_do_nothing(index_elements=["sha256"])
        )
    item = QualityReport(
        id=report.artifact_id,
        user_id=report.binding.user_id,
        sequence=(rows[0].sequence + 1) if rows else 1,
        artifact_sha256=digest,
        report=report.model_dump(mode="json"),
        outcome=result(report),
    )
    session.add(item)
    session.flush()
    return item


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--evidence-directory", type=Path, required=True)
    args = parser.parse_args()
    from app.model_config.connection import ProbeError

    try:
        report, digest, files = load(
            args.artifact, args.sha256, args.evidence_directory
        )
        with Session(engine) as session:
            save(session, report, digest, files)
            session.commit()
    except ValueError, OSError, SQLAlchemyError, ProbeError:
        raise SystemExit(
            "报告未导入：文件、引用、版本或事务检查失败；未运行模型。请本地核对，避免把原件或SQL参数发送到日志。"
        ) from None


if __name__ == "__main__":
    main()
