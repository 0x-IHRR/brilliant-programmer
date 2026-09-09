"""Synthetic complete artifact serialization; not a labelled quality benchmark."""

import copy
import hashlib
import json

import pytest
from sqlmodel import Session

from app.capabilities.catalog import CATALOG, EvidenceKey
from app.core.db import engine
from app.quality.import_report import load
from app.quality.import_report import save as import_report
from app.quality.models import QualityEvidence
from app.quality.rules import Case, Report, Sample, SourceIdentity
from app.training.evaluation_schema import evaluation_inputs
from tests.test_evaluation_schema import example
from tests.test_model_config import account, save
from tests.test_quality_api import report_for


def bundle(tmp_path, owner, config):
    report, _ = report_for(owner, config)
    files = {}

    def put(value):
        raw = (
            value.encode()
            if isinstance(value, str)
            else json.dumps(value, ensure_ascii=False).encode()
        )
        digest = hashlib.sha256(raw).hexdigest()
        files[digest] = raw
        return digest

    cases, samples = [], []
    for domain in CATALOG.domains:
        capability = domain.capabilities[0]
        for difficulty in ("基础", "进阶", "综合"):
            for n in range(2):
                cid = f"{domain.id}-{difficulty}-{n}"
                case, sources, original, grading = example("choice")
                case = case.model_copy(
                    update={
                        "target": EvidenceKey(
                            capability_id=capability.id,
                            difficulty=difficulty,
                            background_id=capability.background_id,
                        ),
                        "title": "合成协议夹具：" + cid,
                    }
                )
                case_hash = put(case.model_dump(mode="json"))
                for source in sources:
                    put(source.text)
                identities = [SourceIdentity.of(s) for s in sources]
                check = put(
                    {
                        "case_sha256": case_hash,
                        "source_checks": [
                            s.model_dump(mode="json") for s in identities
                        ],
                        "rationale": "仅测试绑定协议；未人工核验各领域技术语义",
                    }
                )
                cases.append(
                    Case(
                        id=cid,
                        domain_id=domain.id,
                        difficulty=difficulty,
                        case_sha256=case_hash,
                        sources=identities,
                        human_source_check_sha256=check,
                    )
                )
                for outcome in ("pass", "unclear"):
                    value = copy.deepcopy(grading)
                    if outcome == "unclear":
                        original.answers = [
                            {**original.answers[0], "reason": "不知道，还需要读取证据"}
                        ]
                        value["items"][0].update(
                            conclusion="unclear",
                            gap="仍需了解原理由指向的证据",
                            answer_quotes=[
                                {
                                    "input": "original",
                                    "field": "reason",
                                    "quote": original.answers[0]["reason"],
                                }
                            ],
                        )
                    answer_hash = put(
                        evaluation_inputs([original]).model_dump(mode="json")
                    )
                    jid = case.judgments[0].id
                    annotation = put(
                        {
                            "case_id": cid,
                            "answer_sha256": answer_hash,
                            "judgment_id": jid,
                            "expected": outcome,
                            "critical_safety": domain.id == "security",
                            "rationale": "仅合成协议标签，不是人工评测结果",
                        }
                    )
                    samples.append(
                        Sample(
                            id=f"{cid}-{outcome}",
                            case_id=cid,
                            judgment_id=jid,
                            answer_sha256=answer_hash,
                            annotation_sha256=annotation,
                            output_sha256=put(value),
                            expected=outcome,
                            observed=outcome,
                            critical_safety=domain.id == "security",
                        )
                    )
    report = report.model_copy(update={"cases": cases, "samples": samples})
    report = Report.model_validate_json(report.model_dump_json())
    for digest, raw in files.items():
        (tmp_path / digest).write_bytes(raw)
    path = tmp_path / "report.json"
    path.write_text(report.model_dump_json())
    return path, hashlib.sha256(path.read_bytes()).hexdigest(), report, files


def test_real_local_import_checks_bytes_witnesses_and_retains_private_evidence(
    tmp_path,
):
    owner, auth = account()
    config = save(auth).json()
    path, digest, report, files = bundle(tmp_path, owner, config)
    loaded, actual, retained = load(path, digest, tmp_path)
    assert actual == digest and loaded == report and retained == files
    with Session(engine) as session:
        row = import_report(session, loaded, actual, retained)
        session.commit()
        assert row.outcome == "passed"  # Synthetic result, not real quality evidence.
        for sha, raw in retained.items():
            assert session.get(QualityEvidence, sha).content == raw
    with pytest.raises(ValueError, match="digest"):
        load(path, "0" * 64, tmp_path)
    attachment = tmp_path / report.samples[0].output_sha256
    attachment.write_bytes(b"{}")
    with pytest.raises(ValueError, match="content"):
        load(path, digest, tmp_path)


def test_summary_cannot_disagree_with_actual_item_even_with_updated_report_digest(
    tmp_path,
):
    owner, auth = account()
    config = save(auth).json()
    path, _, report, _ = bundle(tmp_path, owner, config)
    rows = list(report.samples)
    rows[1] = rows[1].model_copy(update={"observed": "pass"})
    path.write_text(report.model_copy(update={"samples": rows}).model_dump_json())
    with pytest.raises(ValueError, match="actual grading"):
        load(path, hashlib.sha256(path.read_bytes()).hexdigest(), tmp_path)


def test_actual_malformed_outputs_are_failures_not_an_unimportable_unknown(tmp_path):
    from app.quality.rules import result

    owner, auth = account()
    config = save(auth).json()
    path, _, report, _ = bundle(tmp_path, owner, config)
    bad = b'{"not_a_grading_result":true}'
    bad_hash = hashlib.sha256(bad).hexdigest()
    (tmp_path / bad_hash).write_bytes(bad)
    rows = list(report.samples)
    for i in (0, 1):
        rows[i] = rows[i].model_copy(
            update={"output_sha256": bad_hash, "observed": "invalid_output"}
        )
    path.write_text(report.model_copy(update={"samples": rows}).model_dump_json())
    loaded, _, _ = load(path, hashlib.sha256(path.read_bytes()).hexdigest(), tmp_path)
    assert result(loaded) == "failed"
