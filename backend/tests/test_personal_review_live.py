"""Existing real worker/TLS paths read back through one owned export."""

from tests import test_evaluations as evaluation
from tests import test_reviews as reviews
from tests.test_accounts import client
from tests.test_draft_collections import read, write

provider = evaluation.provider
ready = evaluation.ready
URL = "/api/v1/personal-review"


def test_original_frozen_grading_dispute_and_three_drafts_preserve_history(
    ready, provider
):
    auth, run, config, answer, *_ = ready
    original = reviews.prepare(ready, provider)
    provider["review"] = lambda context: reviews.reply(context, "disputed")
    reviews.start(auth, run, config)
    result = reviews.wait(auth, run)
    assert result["decision"] == "disputed"
    path = f"/api/v1/training/tasks/{run}/draft"
    initial = read(auth, path)
    original_id = original["inputs"]["original"]["id"]
    for name in ("设备甲", "设备乙", "设备丙"):
        body = write(initial, text=name)
        body["progress"]["based_on_submission_id"] = original_id
        response = client.put(path, headers=auth, json=body)
        assert response.status_code in {200, 409}, response.text
    exported = client.get(URL + "/export", headers=auth)
    assert exported.status_code == 200, exported.text
    snapshot = exported.json()
    row = next(r for r in snapshot["rounds"] if r["task"]["id"] == run)
    assert (
        row["evaluation"] == client.get(evaluation.endpoint(run), headers=auth).json()
    )
    assert row["evaluation"]["inputs"] == original["inputs"]
    assert row["submissions"]["submissions"][0]["answers"] == [answer]
    assert row["review"] == result
    assert len(row["drafts"][0]["versions"]) == 3
    assert len(row["drafts"][0]["unresolved"]) == 3
    assert snapshot["total_points"] == 10
    assert sum(r["points"] for r in snapshot["rewards"]) == 10
    # Reading is not a fresh attempt or a new review/award.
    assert client.get(reviews.endpoint(run), headers=auth).json() == result
