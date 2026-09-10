from tests import test_practices as practice
from tests.test_accounts import client
from tests.test_concepts import publish, receipt

provider = practice.provider
ready = practice.ready
URL = "/api/v1/personal-review"


def test_delivered_demo_text_and_exercise_only_after_actual_receipt(ready, provider):
    auth, run, *_ = ready
    identity = practice.demo(ready)
    before = client.get(URL + "/export", headers=auth)
    assert before.status_code == 200, before.text
    assert before.json()["rounds"][0]["practices"] == []
    publication = publish(auth, run, identity)
    unknown = client.get(URL, headers=auth).json()["rounds"][0]
    assert unknown["help"][0]["deliveries"][0]["status"] == "delivery_unknown"
    assert unknown["help"][0]["deliveries"][0]["delivered_text"] == ""
    assert unknown["practices"] == []
    result = receipt(auth, run, publication)
    assert result.status_code == 200, result.text
    assert result.json()["id"] == identity
    calls = len(provider["requests"])
    response = client.get(URL + "/export", headers=auth)
    assert response.status_code == 200, response.text
    row = response.json()["rounds"][0]
    delivered = row["help"][0]["deliveries"][-1]
    assert delivered["delivered_text"] == "\n\n".join(publication["sections"].values())
    assert (
        row["practices"][0]
        == client.get(practice.url(run, identity), headers=auth).json()
    )
    assert publication["receipt_token"] not in response.text
    assert len(provider["requests"]) == calls
    assert response.json()["total_points"] == 0
