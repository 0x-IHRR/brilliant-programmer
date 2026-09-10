"""This batch on real owner routes/worker/TLS; replies are controlled, not quality scores."""

import json
import uuid

import pytest

from tests.ai_security_benchmarks import comparison, load
from tests.test_accounts import client
from tests.test_concepts import receipt
from tests.test_evaluations import start as start_evaluation
from tests.test_evaluations import wait as wait_evaluation
from tests.test_independent_api import confirmed_publication, controlled_grading
from tests.test_model_config import account, save
from tests.test_practices import guided_coach
from tests.test_submissions import wait_submission
from tests.test_training import provider as provider
from tests.test_training import start_worker, stop_worker, wait_run

batch, sources = load()
BASIC = [d for d in batch.cases if d.candidate.target.difficulty == "基础"]


def configure(supplier, draft, *, variant=False, rename=False):
    supplier["source_text"] = (
        "Controlled transport, not the upstream official server. Observations are teaching assumptions.\n"
        + "\n\n".join(
            f"Original URL: {sources[k].url}\nVersion: {sources[k].version}\n"
            f"Locator and marked AI summary: {sources[k].locator}\n"
            f"Separate exact excerpts:\n{sources[k].text}"
            for k in draft.source_ids
        )
    )
    case = draft.positive_variant if variant else draft.candidate
    if rename:
        case = case.model_copy(update={"title": draft.cosmetic_title})

    def generated(payload):
        context = json.loads(payload["messages"][1]["content"])
        if "new" in context:
            return {
                "comparisons": [
                    {
                        "seen_run_id": seen["run_id"],
                        "seen_judgment_id": "j1",
                        "new_judgment_id": "j1",
                        "relation": "same_scenario",
                        "changes": [],
                    }
                    if rename
                    else comparison(draft, uuid.UUID(seen["run_id"])).model_dump(
                        mode="json"
                    )
                    for seen in context["seen"]
                ]
            }
        transported = "\n".join(s["text"] for s in context["sources"])
        for k in draft.source_ids:
            for field in (
                sources[k].url,
                sources[k].version,
                sources[k].locator,
                sources[k].text,
            ):
                assert field in transported
        value = case.model_dump(mode="json")
        for evidence in value["evidence"]:
            for citation in evidence["citations"]:
                citation["source_id"] = context["sources"][0]["id"]
        return value

    def graded(context):
        result = controlled_grading(context)
        for item in result["items"]:
            answer = next(
                a
                for a in context["inputs"]["original"]
                if a["judgment_id"] == item["judgment_id"]
            )
            rule = next(
                r
                for r in context["task"]["rubric"]
                if r["judgment_id"] == item["judgment_id"]
            )
            failed = answer["value"] == 1
            item.update(
                conclusion="evidenced_fail" if failed else "pass",
                counterexample_quote=rule["counterexample"] if failed else None,
                explanation=rule["reasoning"],
                gap="原答与冻结依据不符。" if failed else None,
            )
        return result

    supplier.update(candidate=generated, grading=graded, coach=guided_coach)


def launch(auth, config, draft, mode):
    response = client.post(
        "/api/v1/capabilities/start",
        headers=auth,
        json={
            "request_id": str(uuid.uuid4()),
            "target": draft.candidate.target.model_dump(),
            "catalog_version": draft.candidate.catalog_version,
            "mode": mode,
            "expected_config_version": config["version"],
            "disclosure_accepted": True,
        },
    )
    assert response.status_code == 202, response.text
    assert response.json()["case"] is None
    return response.json()["id"]


def complete(auth, identity, config, answer):
    response = client.post(
        f"/api/v1/training/tasks/{identity}/submissions",
        headers=auth,
        json={
            "request_id": str(uuid.uuid4()),
            "expected_config_version": config["version"],
            "disclosure_accepted": True,
            "answers": [answer],
        },
    )
    assert response.status_code == 202, response.text
    submitted = wait_submission(auth, identity)
    assert submitted["completed_at"] and submitted["awarded_points"] == 10
    start_evaluation(auth, identity, config)
    result = wait_evaluation(auth, identity)
    assert result["status"] == "completed", result
    return result


@pytest.mark.parametrize("draft", batch.cases, ids=lambda d: d.id)
def test_twelve_independent_source_and_evidence_paths(tmp_path, provider, draft):
    _, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    configure(provider, draft)
    identity = launch(auth, config, draft, "independent")
    process, _ = start_worker(tmp_path, provider, identity)
    try:
        public = wait_run(auth, identity).json()
        assert public["status"] == "completed", public
        assert public["case"]["title"] == draft.candidate.title
        assert "rubric" not in public["case"]
        result = complete(
            auth, identity, config, draft.answers[0].answer.model_dump(mode="json")
        )
        assert result["independent_outcome"] == "independent_pass_candidate", result
        states = client.get("/api/v1/capabilities/evidence", headers=auth).json()[
            "states"
        ]
        assert (
            len(states) == 1
            and states[0]["target"] == draft.candidate.target.model_dump()
        )
        assert states[0]["streak"] == 1 and states[0]["status"] == "unverified"
        assert (
            states[0]["history"][0]["evidence"]["semantic_reliability"] == "unverified"
        )
        assert len(provider["requests"]) == 4
    finally:
        stop_worker(process)


@pytest.mark.parametrize("draft", BASIC, ids=lambda d: d.id)
def test_four_ordinary_errors_preserve_round_award(tmp_path, provider, draft):
    _, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    configure(provider, draft)
    identity = launch(auth, config, draft, "practice")
    process, _ = start_worker(tmp_path, provider, identity)
    try:
        assert wait_run(auth, identity).json()["status"] == "completed"
        result = complete(
            auth, identity, config, draft.answers[1].answer.model_dump(mode="json")
        )
        assert result["result"]["items"][0]["conclusion"] == "evidenced_fail"
        assert result["independent_outcome"] is None
        assert wait_submission(auth, identity)["awarded_points"] == 10
    finally:
        stop_worker(process)


@pytest.mark.parametrize("draft", BASIC[::2], ids=lambda d: d.id)
def test_two_domains_seen_rename_and_directional_delivery(tmp_path, provider, draft):
    _, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    configure(provider, draft)
    original = launch(auth, config, draft, "practice")
    process, _ = start_worker(tmp_path, provider, original)
    try:
        assert wait_run(auth, original).json()["status"] == "completed"

        def check():
            response = client.post(
                f"/api/v1/training/tasks/{original}/independent",
                headers=auth,
                json={
                    "request_id": str(uuid.uuid4()),
                    "expected_config_version": config["version"],
                    "disclosure_accepted": True,
                },
            )
            assert response.status_code == 202, response.text
            return response.json()["id"]

        configure(provider, draft, rename=True)
        rejected = wait_run(auth, check()).json()
        assert rejected["status"] == "failed" and rejected["case"] is None
        configure(provider, draft, variant=True)
        identity = check()
        assert wait_run(auth, identity).json()["status"] == "completed"
        publication = confirmed_publication((auth, identity, config))
        assert receipt(auth, identity, publication).status_code == 200
        result = complete(
            auth,
            identity,
            config,
            {
                "judgment_id": "j1",
                "value": 0,
                "reason": draft.positive_variant.rubric[0].reasoning,
            },
        )
        assert result["independent_outcome"] == "practice"
        states = client.get("/api/v1/capabilities/evidence", headers=auth).json()[
            "states"
        ]
        assert all(s["streak"] == 0 for s in states)
    finally:
        stop_worker(process)
