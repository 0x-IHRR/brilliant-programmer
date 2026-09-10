"""Owned real PostgreSQL exports; no network calls are needed to read history."""

import json
import uuid
from datetime import UTC, datetime

from sqlmodel import Session, select

from app.core.db import engine
from app.training.concept_models import ConceptHelp, HelpDelivery
from app.training.draft_collection import DraftCollection
from app.training.draft_models import TrainingDraft
from app.training.models import TrainingRun
from tests.test_accounts import client
from tests.test_guided import frozen as frozen_case
from tests.test_model_config import account

frozen = frozen_case
URL = "/api/v1/personal-review"


def seed(owner, frozen):
    case, sources = frozen
    with Session(engine) as session:
        row = TrainingRun(
            user_id=owner,
            config_version=uuid.uuid4(),
            destination="https://example.com/v1",
            model_id="synthetic",
            target=case.target.model_dump(),
            selection={"entry": "random"},
            candidate=case.model_dump(mode="json"),
            sources=[s.model_dump() for s in sources],
            status="completed",
        )
        session.add(row)
        session.commit()
        return row.id


def test_owner_export_no_hidden_answers_secrets_or_write_side_effect(frozen):
    owner, auth = account()
    _, other = account()
    run = seed(owner, frozen)
    with Session(engine) as session:
        session.add(
            TrainingDraft(
                run_id=run,
                version=uuid.uuid4(),
                request_id=uuid.uuid4(),
                saved_at=datetime.now(UTC),
                progress={
                    "answers": [
                        {
                            "judgment_id": "j1",
                            "value": None,
                            "reason": "saved incomplete",
                        }
                    ],
                    "step": "materials",
                    "based_on_submission_id": None,
                },
            )
        )
        session.commit()
    response = client.get(URL + "/export", headers=auth)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert "attachment" in response.headers["content-disposition"]
    result = json.loads(response.content)
    assert result["user_id"] == str(owner)
    assert result["rounds"][0]["task"]["id"] == str(run)
    assert (
        result["rounds"][0]["drafts"][0]["versions"][0]["progress"]["answers"][0][
            "reason"
        ]
        == "saved incomplete"
    )
    for hidden in (
        "PRIVATE_HELP_BOUNDARY",
        frozen[0].rubric[0].reasoning,
        "receipt_key",
        "authentication_digest",
        "receipt_hash",
        "api_key",
        "encrypted_key",
        "access_token",
    ):
        assert hidden not in response.text
    assert client.get(URL).status_code == 401
    assert client.get(URL, headers=other).json()["rounds"] == []
    # An injected user query cannot change the principal; no ID-based other-user route.
    assert client.get(URL + f"?user_id={owner}", headers=other).json()["rounds"] == []
    assert client.get(URL + f"/{owner}", headers=other).status_code == 404
    assert client.post(URL, headers=auth, json={}).status_code == 405
    with Session(engine) as session:
        assert (
            session.exec(
                select(DraftCollection).where(DraftCollection.run_id == run)
            ).first()
            is None
        )


def test_help_only_actual_delivered_text_and_unknown_not_private_content(frozen):
    owner, auth = account()
    run = seed(owner, frozen)
    with Session(engine) as session:
        help = ConceptHelp(
            run_id=run,
            config_version=uuid.uuid4(),
            destination="https://example.com/v1",
            model_id="fake",
            created_sequence=1,
            request={"question": "公开问题", "depth": "deep", "answers": []},
            status="failed",
            content={"private": "NEVER-PUBLISH-ME"},
        )
        session.add(help)
        session.flush()
        session.add(
            HelpDelivery(
                run_id=run,
                help_id=help.id,
                sequence=2,
                exposure_sequence=2,
                status="delivery_unknown",
                content_hash="version-one",
                receipt_hash="NEVER-EXPORT-CAPABILITY",
            )
        )
        session.add(
            HelpDelivery(
                run_id=run,
                help_id=help.id,
                sequence=3,
                exposure_sequence=2,
                status="partial",
                content_hash="version-one",
                delivered_text="实际交付的这一段",
                direction="neutral",
            )
        )
        session.commit()
    response = client.get(URL, headers=auth)
    assert response.status_code == 200, response.text
    assert "实际交付的这一段" in response.text
    assert (
        "NEVER-PUBLISH-ME" not in response.text
        and "NEVER-EXPORT-CAPABILITY" not in response.text
    )
    row = response.json()["rounds"][0]
    assert row["help"][0]["deliveries"][0]["delivered_text"] == ""
    assert row["practices"] == []


def test_archive_keeps_content_permanent_delete_does_not_restore(frozen):
    owner, auth = account()
    run = seed(owner, frozen)
    response = client.post(
        "/api/v1/records/archive",
        headers=auth,
        json={"kind": "training", "target_id": str(run), "archived": True},
    )
    assert response.status_code == 204, response.text
    result = client.get(URL, headers=auth).json()
    assert result["rounds"][0]["archived"] is True
    assert frozen[0].title in json.dumps(result, ensure_ascii=False)
    preview = client.post(
        "/api/v1/records/deletions/preview",
        headers=auth,
        json={
            "kind": "training",
            "target_id": str(run),
            "password": "local-test-password-only",
        },
    )
    assert preview.status_code == 200, preview.text
    response = client.post(
        f"/api/v1/records/deletions/{preview.json()['id']}/confirm",
        headers=auth,
        json={"confirmation": "永久删除所列资料及副本"},
    )
    assert response.status_code == 200, response.text
    response = client.get(URL + "/export", headers=auth)
    assert response.status_code == 200, response.text
    assert response.json()["rounds"] == []
    assert response.json()["deleted"] == [{"kind": "training", "object_id": str(run)}]
    assert frozen[0].title not in response.text
    assert (
        "authentication_digest" not in response.text
        and "receipt_hash" not in response.text
    )


def test_whole_export_uses_one_snapshot_across_concurrent_saved_progress(
    frozen, monkeypatch
):
    from app.personal import routes

    owner, auth = account()
    run = seed(owner, frozen)
    original = routes.task_view
    crossed = False

    def crossing(session, row):
        nonlocal crossed
        value = original(session, row)
        if not crossed:
            crossed = True
            with Session(engine) as writer:
                current = writer.get(TrainingRun, run)
                current.message = "new committed message"
                writer.add(current)
                writer.add(
                    TrainingDraft(
                        run_id=run,
                        version=uuid.uuid4(),
                        request_id=uuid.uuid4(),
                        saved_at=datetime.now(UTC),
                        progress={
                            "answers": [],
                            "step": "coach",
                            "based_on_submission_id": None,
                        },
                    )
                )
                writer.commit()
        return value

    monkeypatch.setattr(routes, "task_view", crossing)
    before = client.get(URL + "/export", headers=auth)
    assert before.status_code == 200, before.text
    assert before.json()["rounds"][0]["task"]["message"] != "new committed message"
    assert before.json()["rounds"][0]["drafts"] == []
    after = client.get(URL, headers=auth).json()
    assert after["rounds"][0]["task"]["message"] == "new committed message"
    assert after["rounds"][0]["drafts"][0]["versions"][0]["progress"]["step"] == "coach"


def test_model_user_gate_does_not_block_read_snapshot(frozen):
    from concurrent.futures import ThreadPoolExecutor

    from app.model_config.service import lock_owner

    owner, auth = account()
    seed(owner, frozen)
    with Session(engine) as gate:
        lock_owner(gate, owner)
        with ThreadPoolExecutor() as pool:
            future = pool.submit(client.get, URL, headers=auth)
            try:
                response = future.result(timeout=3)
                assert response.status_code == 200, response.text
            finally:
                gate.rollback()
