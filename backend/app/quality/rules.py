"""Compute admission from operator-reviewed artifacts, not client status claims.

The importer is a local operational trust boundary. These checks verify coverage,
identity and arithmetic, not that a human label or model interpretation is true.
The production importer must retain and verify the referenced evidence bytes.
"""

import hashlib
import uuid
from collections import Counter
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.capabilities.catalog import CATALOG, Difficulty
from app.training.schema import Source, Strict, Text

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Outcome = Literal["pass", "evidenced_fail", "unclear"]
QualityStatus = Literal["unverified", "passed", "failed", "version_mismatch"]
QUALITY_RULE = "scoring-admission-v1"


class Binding(Strict):
    user_id: uuid.UUID
    config_version: uuid.UUID
    destination: Text
    model_id: Text
    evaluation_rule: Text


class SourceIdentity(Strict):
    id: Text
    url: Text
    version: Text
    locator: Text
    text_sha256: Digest

    @classmethod
    def of(cls, source: Source) -> SourceIdentity:
        return cls(
            id=source.id,
            url=source.url,
            version=source.version,
            locator=source.locator,
            text_sha256=hashlib.sha256(source.text.encode()).hexdigest(),
        )


class Case(Strict):
    id: Text
    domain_id: Text
    difficulty: Difficulty
    # Hash of the actual frozen case prevents duplicate content under new IDs.
    case_sha256: Digest
    sources: list[SourceIdentity] = Field(min_length=1, max_length=30)
    human_source_check_sha256: Digest


class Sample(Strict):
    id: Text
    case_id: Text
    judgment_id: Text
    answer_sha256: Digest
    annotation_sha256: Digest
    output_sha256: Digest
    expected: Outcome
    observed: Literal["pass", "evidenced_fail", "unclear", "invalid_output"]
    critical_safety: bool


class Report(Strict):
    artifact_id: uuid.UUID
    binding: Binding
    quality_rule: Literal["scoring-admission-v1"]
    corpus_version: Text
    annotation_version: Text
    # A superseding retest is explicit; editing an existing artifact is forbidden.
    supersedes: uuid.UUID | None
    cases: list[Case] = Field(min_length=84, max_length=10000)
    samples: list[Sample] = Field(min_length=168, max_length=100000)

    @model_validator(mode="after")
    def complete(self) -> Report:
        domains = {d.id for d in CATALOG.domains}
        cells: Counter[tuple[str, str]] = Counter(
            (c.domain_id, c.difficulty) for c in self.cases
        )
        if any(c.domain_id not in domains for c in self.cases) or any(
            cells[(domain, difficulty)] < 2
            for domain in domains
            for difficulty in ("基础", "进阶", "综合")
        ):
            raise ValueError("incomplete 14-domain / three-difficulty coverage")
        if len({c.id for c in self.cases}) != len(self.cases) or len(
            {c.case_sha256 for c in self.cases}
        ) != len(self.cases):
            raise ValueError("duplicate case identity or content")
        ids = {c.id for c in self.cases}
        if len({s.id for s in self.samples}) != len(self.samples) or any(
            s.case_id not in ids for s in self.samples
        ):
            raise ValueError("duplicate sample or missing case")
        if len({(s.case_id, s.answer_sha256) for s in self.samples}) != len(
            self.samples
        ):
            raise ValueError("duplicate answer for the same case")
        expected_by_case: dict[str, set[str]] = {cid: set() for cid in ids}
        for sample in self.samples:
            expected_by_case[sample.case_id].add(sample.expected)
        for expected in expected_by_case.values():
            if "pass" not in expected or not expected & {"evidenced_fail", "unclear"}:
                raise ValueError("case needs acceptable and wrong/insufficient answers")
        if not any(s.critical_safety and s.expected != "pass" for s in self.samples):
            raise ValueError("missing critical-safety counterexamples")
        return self


def result(report: Report) -> Literal["passed", "failed"]:
    """A11 trial thresholds; this is not a population error-rate estimate."""
    total = len(report.samples)
    correct = sum(s.expected == s.observed for s in report.samples)
    if correct * 100 < total * 95 or any(
        s.critical_safety and s.expected != "pass" and s.observed == "pass"
        for s in report.samples
    ):
        return "failed"
    domain_for = {c.id: c.domain_id for c in report.cases}
    totals: Counter[str] = Counter()
    corrects: Counter[str] = Counter()
    for sample in report.samples:
        domain = domain_for[sample.case_id]
        totals[domain] += 1
        corrects[domain] += sample.expected == sample.observed
    return (
        "passed"
        if all(corrects[d] * 100 >= n * 90 for d, n in totals.items())
        else "failed"
    )


def applicability(
    report: Report | None, binding: Binding, sources: list[Source] | None
) -> QualityStatus:
    if report is None:
        return "unverified"
    if report.binding != binding:
        return "version_mismatch"
    if sources is None:
        # At admission, acquisition may not have happened. Known failure is a
        # conservative restriction, not a claim about an as-yet-unread source.
        return "failed" if result(report) == "failed" else "unverified"
    if not sources or any(
        SourceIdentity.of(source) not in [s for c in report.cases for s in c.sources]
        for source in sources
    ):
        return "version_mismatch"
    return result(report)
