import uuid
from datetime import UTC, datetime, timedelta

from sqlmodel import Session

from app.core.db import engine
from app.deletion.models import ArchivedObject
from app.training.draft_models import TrainingDraft
from app.training.models import TrainingRun
from tests.test_accounts import client
from tests.test_guided import frozen as frozen_case
from tests.test_model_config import account

frozen = frozen_case


def add_run(session, owner, case, created_at, *, completed=False):
    row = TrainingRun(
        user_id=owner,
        config_version=uuid.uuid4(),
        destination="https://example.com/v1",
        model_id="synthetic",
        target=case.target.model_dump(),
        selection={"entry": "random"},
        candidate=case.model_dump(mode="json"),
        sources=[],
        status="completed",
        created_at=created_at,
        formal_submitted_at=created_at if completed else None,
    )
    session.add(row)
    session.flush()
    return row


def test_continue_prefers_saved_activity_across_full_history_and_excludes_finished_or_hidden(frozen):
    owner, auth = account()
    case, _ = frozen
    now = datetime.now(UTC)
    with Session(engine) as session:
        older = add_run(session, owner, case, now - timedelta(days=3))
        session.add(TrainingDraft(
            run_id=older.id,
            version=uuid.uuid4(), request_id=uuid.uuid4(),
            saved_at=now, progress={"answers": [], "step": "judgments", "based_on_submission_id": None},
        ))
        for offset in range(21):
            add_run(session, owner, case, now - timedelta(days=2, minutes=offset))
        finished = add_run(session, owner, case, now + timedelta(minutes=2), completed=True)
        hidden = add_run(session, owner, case, now + timedelta(minutes=1))
        session.add(ArchivedObject(user_id=owner, kind="training", object_id=hidden.id))
        session.commit()
        older_id, finished_id, hidden_id = older.id, finished.id, hidden.id

    response = client.get("/api/v1/training/tasks/continue", headers=auth)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["run_id"] == str(older_id)
    assert response.json()["title"] == case.title
    assert str(finished_id) not in response.text and str(hidden_id) not in response.text

    _, empty_auth = account()
    assert client.get("/api/v1/training/tasks/continue", headers=empty_auth).json() is None
