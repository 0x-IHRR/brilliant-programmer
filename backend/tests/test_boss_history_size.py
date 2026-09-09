"""Read-only wire-size experiment, NOT the production history/novelty protocol.

Keep every run and every judgment pair. Exact repeated JSON values may share a
reference; equality never grants novelty. Decoder expansion still goes through
assess_novelty. Real provider context/reliability/120s and crash restoration remain
integration work; synthetic compression ratios are not capacity certification.
"""

import json
import uuid

from app.training.independent_novelty import ScenarioComparison, assess_novelty
from app.training.schema import Candidate
from tests.test_guided import frozen
from tests.test_independent_novelty import variant


def size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())


def reference_rows(rows):
    """Per-field exact value tables; no truncation or semantic deduplication."""
    tables, indices, result = {}, {}, []
    fields = list(rows[0]) if rows else []
    for row in rows:
        assert list(row) == fields
        refs = []
        for field, value in row.items():
            table = tables.setdefault(field, [])
            index = indices.setdefault(field, {})
            literal = json.dumps(value, sort_keys=True, ensure_ascii=False)
            if literal not in index:
                index[literal] = len(table)
                table.append(value)
            refs.append(index[literal])
        result.append(refs)
    return {"fields": fields, "tables": tables, "rows": result}


def expand_rows(document):
    # Prototype only: a production decoder must additionally apply strict schema,
    # index/budget limits and output secret checks before expansion.
    return [
        {
            field: document["tables"][field][index]
            for field, index in zip(document["fields"], row, strict=True)
        }
        for row in document["rows"]
    ]


def fixture(count, old_judgments):
    base, sources = frozen.__wrapped__()
    histories = {}
    for i in range(count):
        data = base.model_dump()
        # Each complete round has a distinct frozen observation; this deliberately
        # does not collapse all 600 histories to one renamed copy.
        data["evidence"][0]["facts"]["retry_deadline_seconds"] = str(i + 1)
        data["rubric"][0]["reasoning"] += (
            f"当前业务允许等待{i + 1}秒，超时后仍须核对持久记录。"
        )
        data["variation"]["causal_condition"] += f"；业务等待期限{i + 1}秒"
        data["judgments"] = [
            dict(data["judgments"][0], id=f"j{j}") for j in range(old_judgments)
        ]
        data["rubric"] = [
            dict(data["rubric"][0], judgment_id=f"j{j}") for j in range(old_judgments)
        ]
        histories[uuid.UUID(int=i + 1)] = Candidate.model_validate(data)
    new, template = variant(base, uuid.UUID(int=1))
    data = new.model_dump()
    data["judgments"] = [dict(data["judgments"][0], id=f"new-{j}") for j in range(4)]
    data["rubric"] = [dict(data["rubric"][0], judgment_id=f"new-{j}") for j in range(4)]
    new = Candidate.model_validate(data)
    comparisons = []
    for run_id, case in histories.items():
        for old in case.judgments:
            rule = next(r for r in case.rubric if r.judgment_id == old.id)
            change = template.changes[0].model_copy(
                update={
                    "before_reasoning": rule.reasoning,
                    "before_variation": case.variation.causal_condition,
                }
            )
            for fresh in new.judgments:
                comparisons.append(
                    template.model_copy(
                        update={
                            "seen_run_id": run_id,
                            "seen_judgment_id": old.id,
                            "new_judgment_id": fresh.id,
                            "changes": [change],
                        }
                    )
                )
    return histories, new, sources, comparisons


def measurement(count=600, old_judgments=3):
    histories, new, sources, comparisons = fixture(count, old_judgments)
    snapshots = [
        {"run_id": str(id), "case": case.model_dump_json()}
        for id, case in histories.items()
    ]
    # Preserve all private frozen fields for storage roundtrip, but do not put this
    # full snapshot on the model wire. Existing context() supplies that whitelist.
    stored_rows = [
        case.model_dump(mode="json") | {"run_id": str(id)}
        for id, case in histories.items()
    ]
    stored = reference_rows(stored_rows)
    assert expand_rows(stored) == stored_rows
    comparison_rows = [c.model_dump(mode="json") for c in comparisons]
    # Factor change fields separately too: every pair remains explicit, while
    # repeated frozen before/after references need not repeat long quotations.
    changes, change_ids = [], {}
    pairs = []
    for row in comparison_rows:
        ids = []
        for change in row["changes"]:
            literal = json.dumps(change, sort_keys=True, ensure_ascii=False)
            if literal not in change_ids:
                change_ids[literal] = len(changes)
                changes.append(change)
            ids.append(change_ids[literal])
        pairs.append(
            {k: v for k, v in row.items() if k != "changes"} | {"change_ids": ids}
        )
    referenced = {"changes": reference_rows(changes), "pairs": reference_rows(pairs)}
    decoded_changes = expand_rows(referenced["changes"])
    expanded = []
    for row in expand_rows(referenced["pairs"]):
        ids = row.pop("change_ids")
        row["changes"] = [decoded_changes[i] for i in ids]
        expanded.append(ScenarioComparison.model_validate_json(json.dumps(row)))
    assert expanded == comparisons
    outcome = assess_novelty(new, sources, histories, expanded, "fake-key")
    assert (
        outcome.status == "novelty_candidate"
        and outcome.semantic_reliability == "unverified"
    )
    assert (
        assess_novelty(new, sources, histories, expanded[:-1], "fake-key").reason
        == "incomplete_comparison"
    )
    return {
        "rounds": count,
        "old_judgments": old_judgments,
        "new_judgments": 4,
        "pairs": len(comparisons),
        "current_storage_bytes": len(json.dumps(snapshots).encode()),
        "referenced_storage_bytes": size(stored),
        "full_comparison_bytes": size(comparison_rows),
        "referenced_comparison_bytes": size(referenced),
    }


def test_all_600_rounds_and_7200_pairs_survive_exact_reference_expansion():
    result = measurement()
    assert result["pairs"] == 7200
    assert result["current_storage_bytes"] > 96 * 1024
    assert result["full_comparison_bytes"] > 1024 * 1024
    # This fixture has repeated facts/rules, not a worst-case bound. If production
    # adopts a protocol it must reject unknown/over-budget input, not drop history.
    assert result["referenced_comparison_bytes"] < result["full_comparison_bytes"]
    assert result["referenced_storage_bytes"] < result["current_storage_bytes"]
