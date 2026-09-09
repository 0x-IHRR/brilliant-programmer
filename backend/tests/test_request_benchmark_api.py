"""Draft matrix through unchanged owner API/queue/TLS; not semantic validation."""

import json
import uuid

import pytest

from tests.request_benchmarks import comparison, load
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


def configure(provider, draft, *, variant=False, cosmetic=False):
    # The TLS server transports exact saved excerpts; its URL is intentionally
    # controlled, not masquerading as the upstream official site.
    provider["source_text"] = (
        "Controlled transport of frozen source records, not the upstream official server. "
        "All scenario observations remain teaching assumptions.\n"
        + "\n\n".join(
            f"Original URL: {sources[k].url}\nVersion: {sources[k].version}\n"
            f"Locator and explicitly marked summary: {sources[k].locator}\n"
            f"Exact excerpts (separate from summary):\n{sources[k].text}"
            for k in draft.source_ids
        )
    )
    candidate = draft.positive_variant if variant else draft.candidate
    if cosmetic:
        candidate = candidate.model_copy(update={"title": draft.cosmetic_variant.title})

    def response(payload):
        context = json.loads(payload["messages"][1]["content"])
        if "new" in context:
            # Current production context deliberately includes only comparison fields.
            records = []
            for seen in context["seen"]:
                if cosmetic:
                    records.append(
                        {
                            "seen_run_id": seen["run_id"],
                            "seen_judgment_id": seen["case"]["judgments"][0]["id"],
                            "new_judgment_id": context["new"]["judgments"][0]["id"],
                            "relation": "same_scenario",
                            "changes": [],
                        }
                    )
                else:
                    # Bind to the real frozen draft and server-assigned prior run.
                    records.append(
                        comparison(
                            draft.candidate,
                            draft.positive_variant,
                            uuid.UUID(seen["run_id"]),
                        ).model_dump(mode="json")
                    )
            return {"comparisons": records}
        value = candidate.model_dump(mode="json")
        for evidence in value["evidence"]:
            evidence["citations"] = [
                {
                    "source_id": context["sources"][0]["id"],
                    "quote": candidate.evidence[0].citations[0].quote,
                }
            ]
        return value

    def grading(context):
        result = controlled_grading(context)
        for item in result["items"]:
            answer = next(
                a
                for a in context["inputs"]["original"]
                if a["judgment_id"] == item["judgment_id"]
            )
            failed = answer["value"] == 1
            item["conclusion"] = "evidenced_fail" if failed else "pass"
            rule = next(
                r
                for r in context["task"]["rubric"]
                if r["judgment_id"] == item["judgment_id"]
            )
            item["counterexample_quote"] = rule["counterexample"] if failed else None
            item["explanation"] = rule["reasoning"]
            item["gap"] = "原答把题面不支持的结论当成事实。" if failed else None
        return result

    provider["candidate"], provider["grading"], provider["coach"] = (
        response,
        grading,
        guided_coach,
    )


def launch(auth, config, draft, mode):
    result = client.post(
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
    assert result.status_code == 202, result.text
    assert result.json()["case"] is None
    return result.json()["id"]


def evaluate(auth, identity, config, candidate, value):
    rule = candidate.rubric[0]
    answer = {
        "judgment_id": candidate.judgments[0].id,
        "value": value,
        "reason": rule.reasoning
        if value == 0
        else "只按表面成功推断全部流程已正确，不需要核对所列边界。",
    }
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
    assert wait_submission(auth, identity)["awarded_points"] == 10
    start_evaluation(auth, identity, config)
    state = wait_evaluation(auth, identity)
    assert state["status"] == "completed", state
    return state


@pytest.mark.parametrize("draft", batch.cases, ids=lambda d: d.id)
def test_all_18_independent_drafts_frozen_evidence_scope(tmp_path, provider, draft):
    _, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    configure(provider, draft)
    identity = launch(auth, config, draft, "independent")
    process, _ = start_worker(tmp_path, provider, identity)
    try:
        result = wait_run(auth, identity).json()
        assert (
            result["status"] == "completed"
            and result["case"]["title"] == draft.candidate.title
        ), result
        assert "rubric" not in result["case"]
        generation = json.loads(provider["requests"][0]["messages"][1]["content"])
        transported = "\n".join(source["text"] for source in generation["sources"])
        for source_id in draft.source_ids:
            source = sources[source_id]
            for field in (source.locator, source.url, source.version, source.text):
                assert field in transported
        evaluated = evaluate(auth, identity, config, draft.candidate, 0)
        assert evaluated["independent_outcome"] == "independent_pass_candidate", (
            evaluated
        )
        evidence = client.get("/api/v1/capabilities/evidence", headers=auth).json()
        assert len(evidence["states"]) == 1
        entry = evidence["states"][0]
        assert entry["target"] == draft.candidate.target.model_dump()
        assert entry["status"] == "unverified" and entry["streak"] == 1
        assert entry["history"][0]["evidence"]["semantic_reliability"] == "unverified"
        assert len(provider["requests"]) == 4
    finally:
        stop_worker(process)


@pytest.mark.parametrize("draft", BASIC, ids=lambda d: d.id)
def test_six_ordinary_families_wrong_but_related_retains_award(
    tmp_path, provider, draft
):
    _, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    configure(provider, draft)
    identity = launch(auth, config, draft, "practice")
    process, _ = start_worker(tmp_path, provider, identity)
    try:
        assert wait_run(auth, identity).json()["status"] == "completed"
        result = evaluate(auth, identity, config, draft.candidate, 1)
        assert result["independent_outcome"] is None
        assert result["result"]["items"][0]["conclusion"] == "evidenced_fail"
        assert wait_submission(auth, identity)["awarded_points"] == 10
    finally:
        stop_worker(process)


@pytest.mark.parametrize("draft", BASIC[::2], ids=lambda d: d.id)
def test_three_domains_real_rename_rejection_variant_and_help(
    tmp_path, provider, draft
):
    _, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    configure(provider, draft)
    original = launch(auth, config, draft, "practice")
    process, _ = start_worker(tmp_path, provider, original)
    try:
        assert wait_run(auth, original).json()["status"] == "completed"

        def new_check():
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

        configure(provider, draft, cosmetic=True)
        rejected = wait_run(auth, new_check()).json()
        assert rejected["status"] == "failed" and rejected["case"] is None
        configure(provider, draft, variant=True)
        identity = new_check()
        accepted = wait_run(auth, identity).json()
        assert accepted["status"] == "completed", accepted
        publication = confirmed_publication((auth, identity, config))
        assert receipt(auth, identity, publication).status_code == 200
        result = evaluate(auth, identity, config, draft.positive_variant, 0)
        assert result["independent_outcome"] == "practice"
        evidence = client.get("/api/v1/capabilities/evidence", headers=auth).json()
        assert all(state["streak"] == 0 for state in evidence["states"])
    finally:
        stop_worker(process)
