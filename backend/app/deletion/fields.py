"""Explicit erasure inventory. IDs, ordering, usage, awards and grants stay intact.

This is deliberately not all string/JSON columns: catalog keys and immutable
financial/qualification identities are not source content. A new content column
must be added here and to the relationship inventory before erasure covers it.
"""

from typing import Any

# Each value is the only replacement permitted by the erasure trigger. Arbitrary
# replacement JSON is never accepted from the deletion API.
FIELDS: dict[str, dict[str, Any]] = {
    "training_run": {
        "selection": {},
        "sources": [],
        "candidate": None,
        "message": "记录已永久删除",
        "stop_requested": True,
        "status": "deleted",
        "code": "deleted",
    },
    "training_submission": {
        "answers": [],
        "relevance": [],
        "message": "记录已永久删除",
        "stop_requested": True,
        "status": "deleted",
        "code": "deleted",
    },
    "training_evaluation": {
        "inputs": {},
        "case_snapshot": {},
        "sources": [],
        "result": None,
        "message": "记录已永久删除",
        "stop_requested": True,
        "status": "deleted",
        "code": "deleted",
    },
    "score_review": {
        "snapshot": {},
        "opinion": None,
        "message": "记录已永久删除",
        "stop_requested": True,
        "status": "deleted",
        "code": "deleted",
    },
    "concept_help": {
        "request": {},
        "content": None,
        "inspection": None,
        "message": "记录已永久删除",
        "stop_requested": True,
        "status": "deleted",
        "code": "deleted",
    },
    "help_delivery": {"delivered_text": ""},
    "training_draft": {"progress": {}},
    "practice_draft": {"progress": {}},
    "draft_collection": {"data": {}},
    "independent_work": {
        "candidate": None,
        "history": [],
        "novelty": None,
        "history_snapshot": None,
        "comparison_plan": None,
        "comparison_results": [],
    },
    "topic_case": {"candidate": {}},
    "topic_version": {"snapshot": {}},
    "topic_job": {
        "input_text": "",
        "candidate": None,
        "message": "来源已永久删除",
        "stop_requested": True,
        "status": "deleted",
        "code": "deleted",
    },
    "jd_document": {"text": ""},
    "jd_analysis": {"snapshot": {}},
    "jd_route": {"snapshot": {}},
    "project_run": {
        "url": "",
        "snapshot": None,
        "project_map": None,
        "message": "来源已永久删除",
        "stop_requested": True,
        "status": "deleted",
        "code": "deleted",
    },
    "project_training_input": {"snapshot": {}, "project_map": {}},
    "project_training_version": {"snapshot": {}},
    "project_training_materials": {"origins": []},
    "quality_report": {"report": {}},
    "quality_evidence": {"content": ""},
}

# A later round's own case/answer is not deleted merely because its comparison
# contains the deleted case. Only comparison copies are erased; proof is unknown.
HISTORY_FIELDS = {
    k: v for k, v in FIELDS["independent_work"].items() if k != "candidate"
}
