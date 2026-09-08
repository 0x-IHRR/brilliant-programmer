import json

import pytest

from app.capabilities.catalog import CATALOG, EvidenceKey
from app.training.schema import Source, public_case, validate_candidate
from tests.test_training import candidate


def example():
    target = EvidenceKey(
        capability_id="network.delivery",
        difficulty="基础",
        background_id="network-evidence-v1",
    )
    sources = [
        Source(
            id="reference-1",
            url="https://example.com/reference",
            version="test-snapshot",
            locator="test excerpt",
            text="Missing acknowledgement does not establish that an operation was not executed. This is a controlled test reference.",
        )
    ]
    value = candidate(
        {
            "messages": [
                {},
                {
                    "content": json.dumps(
                        {
                            "target": target.model_dump(),
                            "catalog_version": CATALOG.version,
                            "sources": [s.model_dump() for s in sources],
                        }
                    )
                },
            ]
        }
    )
    return value, target, sources


@pytest.mark.parametrize(
    "fault",
    [
        "extra",
        "target",
        "version",
        "missing",
        "conflict",
        "quote",
        "source",
        "fact",
        "rubric",
        "judgment",
        "conclusion",
        "key",
    ],
)
def test_candidate_gate_rejects_untrusted_or_incomplete_payload(fault):
    value, target, sources = example()
    if fault == "extra":
        value["execute_tool"] = "grant_admin"
    if fault == "target":
        value["target"]["difficulty"] = "综合"
    if fault == "version":
        value["catalog_version"] = "model-invented"
    if fault == "missing":
        value["missing_evidence"] = ["Cannot establish causality"]
    if fault == "conflict":
        value["conflicts"] = ["Two contradictory observations"]
    if fault == "quote":
        value["evidence"][0]["citations"][0]["quote"] = (
            "invented quote that has no source"
        )
    if fault == "source":
        value["evidence"][0]["citations"][0]["source_id"] = "made-up"
    if fault == "fact":
        conflicting = json.loads(json.dumps(value["evidence"][0]))
        conflicting["id"] = "e2"
        conflicting["facts"]["confirmed"] = "true"
        value["evidence"].append(conflicting)
    if fault == "rubric":
        value["rubric"] = []
    if fault == "judgment":
        value["judgments"][0]["evidence_ids"] = ["missing"]
    if fault == "conclusion":
        value["rubric"][0]["acceptable_options"] = [99]
    if fault == "key":
        value["title"] = "secret-test-key"
    with pytest.raises(ValueError):
        validate_candidate(json.dumps(value), target, sources, "secret-test-key")


@pytest.mark.parametrize("kind", ["choice", "order", "prediction"])
def test_three_judgment_types_have_stable_ids_and_private_rubric(kind):
    value, target, sources = example()
    value["judgments"][0]["kind"] = kind
    rubric = value["rubric"][0]
    if kind != "choice":
        rubric["acceptable_options"] = []
        rubric["acceptable_orders" if kind == "order" else "acceptable_predictions"] = (
            [[1, 0]] if kind == "order" else ["结果未知"]
        )
    validated = validate_candidate(
        json.dumps(value), target, sources, "key-not-present"
    )
    public = public_case(validated, sources).model_dump_json()
    assert '"id":"j1"' in public
    assert "HIDDEN_" not in public
    assert (
        "acceptable_" not in public
        and "rubric" not in public
        and "variation" not in public
    )
