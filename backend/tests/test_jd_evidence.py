"""The JD projection consumes the actual reviewed evidence map in one snapshot."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from tests import test_independent_api
from tests.test_accounts import client
from tests.test_jds import seeded
from tests.test_model_config import account, save

checked = test_independent_api.checked
provider = test_independent_api.provider
frozen = test_independent_api.frozen
origin = test_independent_api.origin


def test_jd_reads_current_review_interpretation_without_rewriting_route(
    checked, provider
):
    from tests.test_review_history import corrected_fail
    from tests.test_reviews import start, wait

    auth, run_id, config = checked
    result = test_independent_api.evaluate(checked)
    assert result["independent_outcome"] == "independent_pass_candidate"
    topic, doc = seeded(auth, config, count=1)
    url = f"/api/v1/jds/{topic}"
    selected = client.post(
        url + "/select", headers=auth, json={"document_id": doc, "role_index": 0}
    )
    assert selected.status_code == 200, selected.text
    before = selected.json()
    assert before["evidence"][0]["streak"] == 1
    assert len(before["evidence"][0]["original_ids"]) == 1
    provider["review"] = corrected_fail
    start(auth, run_id, config)
    reviewed = wait(auth, run_id)
    assert reviewed["decision"] == "corrected", reviewed
    after = client.get(url, headers=auth).json()
    assert after["current"] == before["current"]
    assert after["evidence"][0]["streak"] == 0
    assert after["evidence"][0]["status"] == "unverified"
    assert after["documents"] != []


def test_jd_read_snapshot_does_not_mix_old_route_and_new_versions(monkeypatch):
    from app.training import jds

    _, auth = account()
    config = save(auth).json()
    topic, doc = seeded(auth, config, count=1)
    url = f"/api/v1/jds/{topic}"
    before = client.post(
        url + "/select", headers=auth, json={"document_id": doc, "role_index": 0}
    ).json()
    entered, release = Event(), Event()
    original = jds.read_evidence

    def pause(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(jds, "read_evidence", pause)
    with ThreadPoolExecutor(1) as pool:
        reading = pool.submit(client.get, url, headers=auth)
        assert entered.wait(3)
        try:
            route = before["current"]["route"]
            node = route["nodes"][0]
            changed = client.post(
                f"/api/v1/topics/{topic}/edit",
                headers=auth,
                json={
                    "expected_version": route["id"],
                    "operation": "edit",
                    "node_id": node["id"],
                    "goal": {
                        "target": node["target"],
                        "text": node["text"],
                        "focus": str(uuid.uuid4()),
                    },
                },
            )
            assert changed.status_code == 200, changed.text
        finally:
            release.set()
        response = reading.result(timeout=3)
    assert response.status_code == 200
    assert response.json() == before
    monkeypatch.setattr(jds, "read_evidence", original)
    latest = client.get(url, headers=auth).json()
    assert latest["current"]["route"]["id"] != before["current"]["route"]["id"]
    assert len(latest["topic"]["versions"]) == 2
