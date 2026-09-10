"""Owner report copies with shared byte storage; SHA identifies bytes, not owners."""

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlmodel import Session, col, select

from app.deletion.scope import Scope, references
from app.quality.models import QualityEvidence, QualityReport
from app.quality.rules import Report
from app.training.schema import Candidate


def hashes(raw: dict[str, Any]) -> set[str]:
    report = Report.model_validate_json(json.dumps(raw))
    return (
        {h for c in report.cases for h in (c.case_sha256, c.human_source_check_sha256)}
        | {
            h
            for s in report.samples
            for h in (s.answer_sha256, s.annotation_sha256, s.output_sha256)
        }
        | {s.text_sha256 for c in report.cases for s in c.sources}
    )


def lock_hashes(session: Session, values: set[str]) -> None:
    # Sorted per-blob transaction locks also used by the only import writer.
    # They do not lock another account or hold an account lock across model IO.
    for value in sorted(values):
        key = int.from_bytes(bytes.fromhex(value[:16]), "big", signed=True)
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def attach(session: Session, user_id: uuid.UUID, scope: Scope) -> None:
    identities = set(map(str, scope.roots["training"]))
    cases = []
    texts: set[str] = set()
    for (table, _), patch in list(scope.patches.items()):
        row = patch.row.model_dump()
        if table == "training_submission":
            identities.add(str(row["id"]))
        if table in {"jd_document", "topic_job"}:
            value = row["text" if table == "jd_document" else "input_text"]
            if value:
                texts.add(value)
        if table in {"project_run", "project_training_input"} and row["snapshot"]:
            texts.update(
                fragment["text"]
                for fragment in row["snapshot"].get("fragments", [])
                if isinstance(fragment, dict) and isinstance(fragment.get("text"), str)
            )
        if table == "training_run":
            if row["candidate"]:
                cases.append(row["candidate"])
            texts.update(
                s["text"]
                for s in row["sources"]
                if isinstance(s, dict) and isinstance(s.get("text"), str)
            )
    reports = session.exec(
        select(QualityReport).where(QualityReport.user_id == user_id)
    ).all()
    for report in reports:
        if not report.report:
            continue
        linked = hashes(report.report)
        files = session.exec(
            select(QualityEvidence).where(col(QualityEvidence.sha256).in_(linked))
        ).all()
        matched = False
        for blob in files:
            try:
                raw = blob.content.decode("utf-8")
                if raw in texts:
                    matched = True
                parsed = json.loads(raw)
                if references(parsed, identities):
                    matched = True
                if isinstance(parsed, dict) and any(parsed == case for case in cases):
                    matched = True
                # Source-check and output artifacts are reached by their bound
                # report once an exact case/source/original-input match exists.
                if isinstance(parsed, dict) and "judgments" in parsed:
                    normalized = Candidate.model_validate(parsed).model_dump(
                        mode="json"
                    )
                    if any(normalized == case for case in cases):
                        matched = True
            except ValueError, UnicodeError:
                continue
        if matched:
            scope.add(report)
            scope.roots.setdefault("quality", set()).add(report.id)
            # Global blob rows are deliberately not put in per-owner erase rows:
            # another owner may legally import the same public bytes later.


def erase_unreferenced(session: Session, candidates: set[str]) -> None:
    lock_hashes(session, candidates)
    for sha in sorted(candidates):
        used = session.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM quality_report WHERE jsonb_path_exists(report::jsonb, '$.** ? (@ == $sha)', jsonb_build_object('sha', CAST(:sha AS text))))"
            ),
            {"sha": sha},
        ).scalar_one()
        if not used:
            session.execute(
                text("DELETE FROM quality_evidence WHERE sha256=:sha"), {"sha": sha}
            )
