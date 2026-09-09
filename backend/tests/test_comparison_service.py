"""Persisted JSON adapters must use the same UTF-8 bounds as the snapshot."""

import json
import uuid

from app.training.comparison_service import frozen_history
from app.training.history_protocol import SNAPSHOT_BYTES, freeze_history
from app.training.independent_models import IndependentWork
from tests.test_guided import frozen


def test_persisted_chinese_snapshot_uses_canonical_utf8_not_ascii_expansion():
    case, _ = frozen.__wrapped__()
    history = {
        uuid.UUID(int=i + 1): case.model_copy(
            update={"task": "请核对材料中的执行证据。" * 380 + str(i)}
        )
        for i in range(300)
    }
    snapshot = freeze_history(history)
    data = snapshot.model_dump(mode="json")
    assert (
        len(snapshot.model_dump_json().encode())
        < SNAPSHOT_BYTES
        < len(json.dumps(data).encode())
    )
    work = IndependentWork(run_id=uuid.uuid4(), history_snapshot=data)
    assert frozen_history(work) == history
