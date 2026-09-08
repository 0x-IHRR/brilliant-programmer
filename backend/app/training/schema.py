"""Candidates are data, never instructions. Public output is an explicit allowlist."""

import hashlib
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.capabilities.catalog import CATALOG, EvidenceKey
from app.model_config.output import check_output

Text = Annotated[str, Field(min_length=1, max_length=6000, pattern=r"\S")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Source(Strict):
    id: Text
    url: Text
    version: Text
    locator: Text
    text: Text


class Citation(Strict):
    source_id: Text
    quote: Text


class Evidence(Strict):
    id: Text
    label: Literal["教学材料"]
    text: Text
    # Same property cannot silently have contradictory values in one scenario.
    facts: dict[str, str] = Field(min_length=1, max_length=30)
    citations: list[Citation] = Field(min_length=1, max_length=10)


class Judgment(Strict):
    id: Text
    kind: Literal["choice", "order", "prediction"]
    prompt: Text
    options: list[Text] = Field(min_length=2, max_length=6)
    evidence_ids: list[Text] = Field(min_length=1, max_length=10)


class Rubric(Strict):
    judgment_id: Text
    acceptable_options: list[int] = Field(default_factory=list, max_length=6)
    acceptable_orders: list[list[int]] = Field(default_factory=list, max_length=6)
    acceptable_predictions: list[Text] = Field(default_factory=list, max_length=6)
    reasoning: Text
    evidence_ids: list[Text] = Field(min_length=1, max_length=10)
    counterexample: Text
    help_boundary: Text


class Variation(Strict):
    causal_condition: Text
    expected_evidence: Text
    decision_effect: Text


class Candidate(Strict):
    target: EvidenceKey
    catalog_version: Text
    title: Text
    task: Text
    assumptions: list[Text] = Field(min_length=1, max_length=12)
    evidence: list[Evidence] = Field(min_length=1, max_length=12)
    judgments: list[Judgment] = Field(min_length=1, max_length=4)
    rubric: list[Rubric] = Field(min_length=1, max_length=4)
    variation: Variation
    missing_evidence: list[Text] = Field(max_length=12)
    conflicts: list[Text] = Field(max_length=12)


def validate_candidate(
    raw: str, target: EvidenceKey, sources: list[Source], key: str
) -> Candidate:
    check_output(raw, key)
    candidate = Candidate.model_validate_json(raw)
    if candidate.target != target or candidate.catalog_version != CATALOG.version:
        raise ValueError("target changed")
    if candidate.missing_evidence or candidate.conflicts:
        raise ValueError("insufficient or conflicting evidence")
    source_by_id = {source.id: source for source in sources}
    evidence_ids = {e.id for e in candidate.evidence}
    judgment_ids = {j.id for j in candidate.judgments}
    if len(evidence_ids) != len(candidate.evidence) or len(judgment_ids) != len(
        candidate.judgments
    ):
        raise ValueError("duplicate identity")
    facts: dict[str, str] = {}
    for evidence in candidate.evidence:
        for citation in evidence.citations:
            source = source_by_id.get(citation.source_id)
            if (
                source is None
                or citation.quote not in source.text
                or len(citation.quote.strip()) < 20
            ):
                raise ValueError("unverified citation")
        for name, value in evidence.facts.items():
            if (
                not name.strip()
                or not value.strip()
                or (name in facts and facts[name] != value)
            ):
                raise ValueError("conflicting facts")
            facts[name] = value
    if (
        len(candidate.rubric) != len(judgment_ids)
        or {r.judgment_id for r in candidate.rubric} != judgment_ids
    ):
        raise ValueError("incomplete rubric")
    by_id = {j.id: j for j in candidate.judgments}
    for judgment in candidate.judgments:
        if not set(judgment.evidence_ids) <= evidence_ids or len(
            set(judgment.options)
        ) != len(judgment.options):
            raise ValueError("invalid judgment")
    for rubric in candidate.rubric:
        if not set(rubric.evidence_ids) <= set(by_id[rubric.judgment_id].evidence_ids):
            raise ValueError("unsupported conclusion")
        judgment = by_id[rubric.judgment_id]
        if judgment.kind == "choice" and (
            not rubric.acceptable_options
            or rubric.acceptable_orders
            or rubric.acceptable_predictions
        ):
            raise ValueError("missing choice conclusion")
        if judgment.kind == "order" and (
            not rubric.acceptable_orders
            or rubric.acceptable_options
            or rubric.acceptable_predictions
            or any(
                sorted(order) != list(range(len(judgment.options)))
                for order in rubric.acceptable_orders
            )
        ):
            raise ValueError("invalid expected ordering")
        if judgment.kind == "prediction" and (
            not rubric.acceptable_predictions
            or rubric.acceptable_orders
            or rubric.acceptable_options
        ):
            raise ValueError("missing expected prediction")
        if any(
            type(option) is not int
            or not 0 <= option < len(by_id[rubric.judgment_id].options)
            for option in rubric.acceptable_options
        ):
            raise ValueError("invalid conclusion")
    return candidate


class PublicEvidence(Strict):
    id: Text
    label: Literal["教学材料"]
    text: Text
    citations: list[Citation]


class PublicCase(Strict):
    target: EvidenceKey
    catalog_version: Text
    title: Text
    task: Text
    assumptions: list[Text]
    evidence: list[PublicEvidence]
    judgments: list[Judgment]
    sources: list[Source]
    quality: str = (
        "来源定位与结构已校验；真实模型教学质量、变式准确性未验收。评分可靠性未验证。"
    )


def public_case(candidate: Candidate, sources: list[Source]) -> PublicCase:
    return PublicCase(
        target=candidate.target,
        catalog_version=candidate.catalog_version,
        title=candidate.title,
        task=candidate.task,
        assumptions=candidate.assumptions,
        evidence=[
            PublicEvidence(id=e.id, label=e.label, text=e.text, citations=e.citations)
            for e in candidate.evidence
        ],
        judgments=candidate.judgments,
        sources=sources,
    )


def scenario_fingerprint(candidate: Candidate) -> str:
    # ponytail: exact causal/evidence identity rejects repeats; semantic novelty needs #40's quality gate and #35–39 human-labelled materials.
    value = candidate.variation.model_dump_json() + str(
        sorted((k, v) for e in candidate.evidence for k, v in e.facts.items())
    )
    return hashlib.sha256(value.encode()).hexdigest()
