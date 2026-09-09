"""Synthetic arithmetic/binding fixtures, never human quality evidence."""

import hashlib
import uuid

import pytest
from pydantic import ValidationError

from app.capabilities.catalog import CATALOG
from app.quality.rules import Binding, Report, applicability, result
from app.training.schema import Source


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def fixture() -> tuple[Report, Source]:
    source = Source(
        id="s",
        url="https://example.com/reference",
        version="v1",
        locator="1",
        text="controlled source",
    )
    cases = []
    samples = []
    for domain in CATALOG.domains:
        for difficulty in ("基础", "进阶", "综合"):
            for n in range(2):
                cid = f"{domain.id}-{difficulty}-{n}"
                cases.append(
                    {
                        "id": cid,
                        "domain_id": domain.id,
                        "difficulty": difficulty,
                        "case_sha256": digest(cid),
                        "human_source_check_sha256": digest("synthetic-check"),
                        "sources": [
                            {
                                "id": source.id,
                                "url": source.url,
                                "version": source.version,
                                "locator": source.locator,
                                "text_sha256": digest(source.text),
                            }
                        ],
                    }
                )
                for expected in ("pass", "evidenced_fail"):
                    sid = f"{cid}-{expected}"
                    samples.append(
                        {
                            "id": sid,
                            "case_id": cid,
                            "judgment_id": "j1",
                            "answer_sha256": digest(sid),
                            "annotation_sha256": digest("synthetic-label"),
                            "output_sha256": digest("synthetic-output"),
                            "expected": expected,
                            "observed": expected,
                            "critical_safety": domain.id == "security",
                        }
                    )
    # JSON validates the same strict UUID input format used by the local importer.
    import json

    report = Report.model_validate_json(
        json.dumps(
            {
                "artifact_id": str(uuid.uuid4()),
                "binding": {
                    "user_id": str(uuid.uuid4()),
                    "config_version": str(uuid.uuid4()),
                    "destination": "https://example.com/v1",
                    "model_id": "controlled",
                    "evaluation_rule": "rule-v1",
                },
                "quality_rule": "scoring-admission-v1",
                "corpus_version": "synthetic-v1",
                "annotation_version": "synthetic-v1",
                "supersedes": None,
                "cases": cases,
                "samples": samples,
            }
        )
    )
    return report, source


def test_exact_version_required_and_unknown_is_not_failure() -> None:
    report, source = fixture()
    assert result(report) == "passed"
    assert applicability(None, report.binding, [source]) == "unverified"
    assert applicability(report, report.binding, None) == "unverified"
    assert applicability(report, report.binding, [source]) == "passed"
    assert (
        applicability(
            report, report.binding, [source.model_copy(update={"version": "v2"})]
        )
        == "version_mismatch"
    )
    for field in Binding.model_fields:
        value = uuid.uuid4() if field in {"user_id", "config_version"} else "changed"
        assert (
            applicability(
                report, report.binding.model_copy(update={field: value}), [source]
            )
            == "version_mismatch"
        )


def test_domain_threshold_and_safety_cannot_hide_in_overall_score() -> None:
    report, source = fixture()
    rows = list(report.samples)
    # 166 / 168 still passes the overall threshold, but 10 / 12 fails this domain.
    for i in (0, 1):
        rows[i] = rows[i].model_copy(update={"observed": "unclear"})
    failed = report.model_copy(update={"samples": rows})
    assert result(failed) == "failed"
    assert applicability(failed, report.binding, None) == "failed"
    assert applicability(failed, report.binding, [source]) == "failed"
    rows = list(report.samples)
    i = next(
        i for i, s in enumerate(rows) if s.critical_safety and s.expected != "pass"
    )
    rows[i] = rows[i].model_copy(update={"observed": "pass"})
    assert result(report.model_copy(update={"samples": rows})) == "failed"


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "duplicate_case",
        "duplicate_answer",
        "only_positive",
        "no_safety",
        "client_status",
    ],
)
def test_report_cannot_claim_coverage_or_status(change: str) -> None:
    report, _ = fixture()
    raw = report.model_dump(mode="json")
    if change == "missing":
        raw["cases"].pop()
    elif change == "duplicate_case":
        raw["cases"][1]["case_sha256"] = raw["cases"][0]["case_sha256"]
    elif change == "duplicate_answer":
        raw["samples"][1]["answer_sha256"] = raw["samples"][0]["answer_sha256"]
    elif change == "only_positive":
        raw["samples"][1]["expected"] = "pass"
    elif change == "no_safety":
        for row in raw["samples"]:
            row["critical_safety"] = False
    else:
        raw["status"] = "passed"
    import json

    with pytest.raises(ValidationError):
        Report.model_validate_json(json.dumps(raw))
