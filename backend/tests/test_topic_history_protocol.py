"""Existing confirmed-topic guard survives switching a long history's format."""

import json
import uuid

import pytest
from sqlmodel import Session

from app.core.db import engine
from app.training.history_protocol import ComparisonInput
from app.training.models import TrainingRun
from app.training.schema import Candidate
from tests import test_training
from tests.test_accounts import client
from tests.test_boss_history_size import fixture
from tests.test_history_protocol import response_for
from tests.test_model_config import account, save
from tests.test_project_training_rules import material as material
from tests.test_project_training_rules import selection as project_selection

provider = test_training.provider


@pytest.mark.parametrize("inspection", [True, False, None])
@pytest.mark.parametrize("entry", ["free_topic", "jd", "project"])
def test_full_reference_comparison_keeps_confirmed_topic_inspection(
    tmp_path, provider, inspection, entry, material
):
    owner, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    history, new, sources, comparisons = fixture(70, 1)
    ids = {old: uuid.uuid4() for old in history}
    comparisons = [
        c.model_copy(update={"seen_run_id": ids[c.seen_run_id]}) for c in comparisons
    ]
    goal, focus = "请求确认丢失后的重试", "核对持久执行证据，而非仅看收到确认"
    provenance = (
        {
            "requirement_quote": "处理请求重试",
            "basis": "inferred",
            "simulation_label": "教学模拟",
        }
        if entry == "jd"
        else {}
    )
    transmitted = provenance.copy()
    if entry == "project":
        frozen = project_selection(material)
        frozen = frozen.model_copy(
            update={
                "goal": frozen.goal.model_copy(update={"text": goal, "focus": focus})
            }
        )
        sources = [ref.source for ref in frozen.references]

        def bind(case):
            value = case.model_dump(mode="json")
            for evidence in value["evidence"]:
                for citation in evidence["citations"]:
                    citation["source_id"] = sources[0].id
                    citation["quote"] = sources[0].text
            return Candidate.model_validate_json(json.dumps(value))

        history = {identity: bind(case) for identity, case in history.items()}
        new = bind(new)
        provenance = {"project": frozen.model_dump(mode="json")}
        transmitted = {
            "module_path": frozen.module_path,
            "repository_commit": f"{frozen.repository.owner}/{frozen.repository.name}@{frozen.repository.commit}",
            "simulation_label": "教学模拟",
        }
    with Session(engine) as session:
        for old, case in history.items():
            session.add(
                TrainingRun(
                    id=ids[old],
                    user_id=owner,
                    config_version=uuid.UUID(config["version"]),
                    destination=config["service_url"],
                    model_id=config["model_id"],
                    target=case.target.model_dump(),
                    selection={
                        "entry": entry,
                        "goal": goal,
                        "focus": focus,
                        "catalog_version": "fullstack-v1.0.0",
                        "topic_version_id": str(uuid.uuid4()),
                        "topic_node_id": str(uuid.uuid4()),
                        **provenance,
                        **(
                            {
                                "jd_document_id": str(uuid.uuid4()),
                                "jd_role_name": "后端工程师",
                            }
                            if entry == "jd"
                            else {}
                        ),
                    },
                    candidate=case.model_dump(mode="json"),
                    sources=[s.model_dump(mode="json") for s in sources],
                    status="completed",
                    code="ready",
                )
            )
        session.commit()

    def controlled(payload):
        body = json.loads(payload["messages"][1]["content"])
        if "input" not in body:
            assert body["confirmed_topic"] == {
                "goal": goal,
                "focus": focus,
                **transmitted,
            }
            assert body["sources"] == [
                source.model_dump(mode="json") for source in sources
            ]
            return (
                {
                    "case": new.model_dump(mode="json"),
                    "materials": [
                        {"evidence_id": e.id, "kind": "synthetic_log"}
                        for e in new.evidence
                    ],
                }
                if entry == "project"
                else new.model_dump(mode="json")
            )
        batch = ComparisonInput.model_validate_json(json.dumps(body["input"]))
        assert batch.topic.text == goal and batch.topic.focus == focus
        assert batch.topic.target == new.target and len(batch.runs) == 70
        if entry == "jd":
            assert all(
                batch.topic.model_dump()[key] == value
                for key, value in provenance.items()
            )
        if entry == "project":
            assert batch.topic.module_path == frozen.module_path
            assert "synthetic_log" in batch.topic.material_origins
        result = json.loads(response_for(batch, comparisons))
        if inspection is not None:
            result["topic_coverage"] = {
                "accepted": inspection,
                "explanation": "核对当前确认类型、持久结果与用户要求重点",
            }
        return result

    provider["candidate"] = controlled
    response = client.post(
        f"/api/v1/training/tasks/{next(iter(ids.values()))}/independent",
        headers=auth,
        json={
            "request_id": str(uuid.uuid4()),
            "expected_config_version": config["version"],
            "disclosure_accepted": True,
        },
    )
    assert response.status_code == 202, response.text
    identity = response.json()["id"]
    process, _ = test_training.start_worker(tmp_path, provider, identity)
    try:
        result = test_training.wait_run(auth, identity).json()
        assert result["status"] == ("completed" if inspection else "failed"), result
        assert bool(result["case"]) == bool(inspection)
        assert len(result["attempts"]) == len(provider["requests"]) == 2
        assert result["topic_snapshot"]["focus"] == focus
        if not inspection:
            assert result["code"] == "no_qualified_case"
    finally:
        test_training.stop_worker(process)
