import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from app.training.draft_conflicts import (
    choose_version,
    delete_current,
    differing_fields,
    new_versions,
    require_resolved,
    save_version,
)
from app.training.draft_schema import DraftAnswer, DraftProgress, SaveDraft
from tests.test_drafts import candidate as candidate


def request(text, current=None, step="judgments", based=None):
    return SaveDraft(
        request_id=uuid.uuid4(),
        expected_version=current,
        progress=DraftProgress(
            answers=[DraftAnswer(judgment_id="choice", value=0, reason=text)],
            step=step,
            based_on_submission_id=based,
        ),
    )


def save(state, candidate, body, observed=None, latest=None):
    observed = observed or state
    return save_version(
        state,
        candidate=candidate,
        request=body,
        observed_revision=observed.revision,
        generation=observed.generation,
        latest_submission_id=latest,
        saved_at=datetime.now(UTC),
    )


def conflict(state, candidate):
    before = state
    state, a = save(state, candidate, request("设备 A"))
    state, b = save(state, candidate, request("设备 B", step="coach"), before)
    return state, a, b


def test_three_devices_keep_all_inputs_and_choose_whole_snapshot(candidate):
    initial = new_versions(uuid.uuid4())
    state, a, b = conflict(initial, candidate)
    state, c = save(state, candidate, request("设备 C", step="materials"), initial)
    assert state.unresolved == (a.version, b.version, c.version)
    assert state.current == a.version  # Not a winner while unresolved.
    with pytest.raises(HTTPException) as blocked:
        require_resolved(state)
    assert blocked.value.status_code == 409
    chosen = choose_version(state, observed_revision=state.revision, version=b.version)
    require_resolved(chosen)
    assert chosen.current == b.version and chosen.unresolved == ()
    assert chosen.versions == state.versions  # Selection is not deletion.
    selected = next(item for item in chosen.versions if item.version == chosen.current)
    assert selected.progress == b.progress
    assert selected.progress.step == "coach"
    assert selected.progress.answers[0].reason == "设备 B"


def test_write_during_selection_requires_new_confirmed_collection(candidate):
    initial = new_versions(uuid.uuid4())
    state, a, b = conflict(initial, candidate)
    seen = state
    state, c = save(state, candidate, request("第三份"), initial)
    with pytest.raises(HTTPException) as stale:
        choose_version(state, observed_revision=seen.revision, version=b.version)
    assert stale.value.status_code == 409
    assert {x.version for x in state.versions} == {a.version, b.version, c.version}
    chosen = choose_version(state, observed_revision=state.revision, version=b.version)
    # Reverse serialization: a write based on even the chosen version, but read
    # before selection, cannot overwrite that explicit decision silently.
    again, d = save(chosen, candidate, request("后来输入", b.version), seen)
    assert again.current == b.version and again.unresolved == (b.version, d.version)


def test_lost_response_retry_is_old_receipt_not_new_winner(candidate):
    initial = new_versions(uuid.uuid4())
    body = request("保存后丢响应")
    state, first = save(initial, candidate, body)
    state, second = save(state, candidate, request("后来版本", first.version))
    unchanged, receipt = save(state, candidate, body, initial)
    assert unchanged == state and receipt.version == first.version
    assert unchanged.current == second.version and not unchanged.unresolved
    body.progress.answers[0] = body.progress.answers[0].model_copy(
        update={"reason": "更改请求内容"}
    )
    with pytest.raises(HTTPException):
        save(state, candidate, body, initial)


def test_delete_first_rejects_both_old_current_and_initial_device(candidate):
    initial = new_versions(uuid.uuid4())
    state, a = save(initial, candidate, request("待删除"))
    deleted = delete_current(state, observed_revision=state.revision, version=a.version)
    assert deleted.versions == () and deleted.current is None
    assert deleted.generation != state.generation
    for seen, body in [
        (state, request("旧设备", a.version)),
        (initial, request("首次未保存")),
    ]:
        with pytest.raises(HTTPException) as stale:
            save(deleted, candidate, body, seen)
        assert stale.value.status_code == 409
    fresh, new = save(deleted, candidate, request("读取删除状态后明确开始"))
    assert fresh.current == new.version


def test_save_first_blocks_stale_delete_and_does_not_remove_other_versions(candidate):
    initial = new_versions(uuid.uuid4())
    state, a = save(initial, candidate, request("A"))
    seen = state
    state, b = save(state, candidate, request("B", a.version))
    with pytest.raises(HTTPException):
        delete_current(state, observed_revision=seen.revision, version=a.version)
    with pytest.raises(HTTPException):
        delete_current(state, observed_revision=state.revision, version=a.version)
    deleted = delete_current(state, observed_revision=state.revision, version=b.version)
    assert deleted.versions == (a,) and deleted.current is None
    # Historical retention alone is not an unresolved conflict.
    require_resolved(deleted)


def test_delete_current_in_conflict_keeps_remaining_version_unresolved(candidate):
    state, a, b = conflict(new_versions(uuid.uuid4()), candidate)
    deleted = delete_current(state, observed_revision=state.revision, version=a.version)
    assert deleted.versions == (b,) and deleted.unresolved == (b.version,)
    with pytest.raises(HTTPException):
        require_resolved(deleted)
    chosen = choose_version(
        deleted, observed_revision=deleted.revision, version=b.version
    )
    assert chosen.current == b.version
    require_resolved(chosen)


def test_select_old_lineage_does_not_rebase_or_change_formal_facts(candidate):
    state, a = save(new_versions(uuid.uuid4()), candidate, request("原答草稿"))
    latest = uuid.uuid4()
    state, b = save(
        state, candidate, request("补充草稿", a.version, based=latest), latest=latest
    )
    chosen = choose_version(state, observed_revision=state.revision, version=a.version)
    assert chosen.versions[0].progress.based_on_submission_id is None
    assert chosen.versions[1].progress.based_on_submission_id == latest
    with pytest.raises(HTTPException):
        save(chosen, candidate, request("继续旧草稿", a.version), latest=latest)
    assert chosen.current == a.version and b in chosen.versions


def test_differences_use_judgment_identity_not_array_position():
    a = DraftAnswer(judgment_id="choice", value=0, reason="一")
    b = DraftAnswer(judgment_id="order", value=[1, 0], reason="二")
    left = DraftProgress(answers=[a, b])
    right = DraftProgress(answers=[b, a])
    assert differing_fields(left, right) == ()
    right = right.model_copy(deep=True)
    right.answers[0] = right.answers[0].model_copy(update={"reason": "新理由"})
    right = right.model_copy(update={"step": "coach"})
    assert differing_fields(left, right) == ("step", "answers.order")
    assert left.answers[1].reason == "二"


def test_failed_validation_has_no_proposed_save_and_input_is_not_mutated(candidate):
    state = new_versions(uuid.uuid4())
    body = request("本机保留")
    body.progress.answers[0] = body.progress.answers[0].model_copy(
        update={"judgment_id": "unknown"}
    )
    with pytest.raises(ValueError):
        save(state, candidate, body)
    assert state.versions == () and body.progress.answers[0].reason == "本机保留"
    valid = request("正常")
    proposed, receipt = save(state, candidate, valid)
    # A failed DB commit later leaves the original state. Pure return != saved.
    assert state.versions == ()
    receipt.progress.answers.clear()
    valid.progress.answers.clear()
    assert proposed.versions[0].progress.answers[0].reason == "正常"


def test_original_and_each_practice_have_independent_collections(candidate):
    run = uuid.uuid4()
    original = new_versions(run)
    practice_a = new_versions(run, uuid.uuid4())
    practice_b = new_versions(run, uuid.uuid4())
    state, a, _ = conflict(practice_a, candidate)
    assert state.help_id == practice_a.help_id
    for other in [original, practice_b]:
        require_resolved(other)
        with pytest.raises(HTTPException):
            choose_version(other, observed_revision=other.revision, version=a.version)
        with pytest.raises(HTTPException):
            save(other, candidate, request("错 scope"), state)
        assert other.versions == ()
