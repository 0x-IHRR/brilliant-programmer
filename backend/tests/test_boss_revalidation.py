"""Real review → linked new Boss → retained level, on dedicated PostgreSQL/TLS."""

import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlmodel import Session, select

from app.core.db import engine
from app.model_config.service import lock_owner
from app.models import User
from app.training.boss import FIRST_STAGE
from app.training.boss_models import BossAttempt, BossPromotion, BossRevalidation
from app.training.boss_service import mark_reviewed_promotion
from app.training.evaluation_models import Evaluation
from app.training.independent_service import record_frozen
from app.training.models import TrainingRun
from app.training.review_models import ScoreReview
from tests import boss_scenarios, test_training
from tests.test_accounts import client
from tests.test_boss_api import answer, seed_points
from tests.test_boss_api import start as boss_start
from tests.test_evaluations import wait as wait_evaluation
from tests.test_model_config import account, save
from tests.test_reviews import consent, marker, options
from tests.test_reviews import start as review_start
from tests.test_reviews import wait as wait_review
from tests.test_submissions import wait_submission

provider = test_training.provider


def corrected(context):
    result = boss_scenarios.grade(context)
    item = result["items"][0]
    item.update(
        conclusion="evidenced_fail",
        interpreted_reasoning=1,
        gap="原理由直接断定成功，没有核对失败阶段",
        counterexample_quote=context["task"]["rubric"][0]["counterexample"],
    )
    return {
        "decision": "corrected",
        "explanation": "重新对照同一冻结理由和原反例",
        "grading": result,
    }


def access(auth):
    result = client.get("/api/v1/boss/access", headers=auth)
    assert result.status_code == 200, result.text
    return result.json()


def replay(owner, identity):
    with Session(engine) as session:
        lock_owner(session, owner)
        run = session.get(TrainingRun, uuid.UUID(identity))
        record_frozen(session, run, session.get(Evaluation, run.id))
        session.commit()


def test_real_confirmed_promotion_review_new_same_stage_only_resolves(
    tmp_path, provider
):
    owner, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    seed_points(owner, config, 100)
    provider.update(
        candidate=boss_scenarios.candidate,
        grading=boss_scenarios.grade,
        review=corrected,
        source_text=boss_scenarios.REFERENCE,
    )
    response = boss_start(auth, config)
    assert response.status_code == 202, response.text
    original = response.json()["id"]
    process, control = test_training.start_worker(tmp_path, provider, original)
    try:
        assert test_training.wait_run(auth, original).json()["status"] == "completed"
        answer(auth, original, config)
        assert wait_submission(auth, original)["awarded_points"] == 10
        assert wait_evaluation(auth, original)["status"] == "completed"
        promoted = client.get(f"/api/v1/boss/tasks/{original}", headers=auth).json()
        assert promoted["current_level"] == "初级程序员" and promoted["promotion_id"]
        assert access(auth)["revalidations"] == []
        options(control, review_before_settle=True)
        review_start(auth, original, config)
        marker(control, ".review_settling")
        assert access(auth)["revalidations"] == []
        replay(owner, original)
        assert access(auth)["revalidations"] == []
        options(control, review_before_settle=False)
        reviewed = wait_review(auth, original)
        assert reviewed["decision"] == "corrected", reviewed
        state = access(auth)
        assert state["level"] == "初级程序员" and state["points"] == 110
        pending = state["revalidations"][0]
        assert pending["status"] == "required"
        assert pending["promotion_id"] == promoted["promotion_id"]
        assert pending["stage"] == FIRST_STAGE.model_dump(mode="json")
        _, other_auth = account()
        other_config = save(other_auth, service_url=provider["url"]).json()
        assert (
            boss_start(
                other_auth,
                other_config,
                revalidation_of=pending["promotion_id"],
                expected_revalidation_event_id=pending["current_event_id"],
            ).status_code
            == 409
        )
        assert (
            client.get(f"/api/v1/boss/tasks/{original}", headers=other_auth).status_code
            == 404
        )
        assert (
            boss_start(
                auth, config, expected_revalidation_event_id=pending["current_event_id"]
            ).status_code
            == 422
        )
        provider["candidate"] = lambda payload: boss_scenarios.candidate(payload, 1)
        body = {
            **consent(config),
            "request_id": str(uuid.uuid4()),
            "expected_stage": pending["stage"],
            "revalidation_of": pending["promotion_id"],
            "expected_revalidation_event_id": pending["current_event_id"],
        }
        response = client.post("/api/v1/boss/start", headers=auth, json=body)
        assert response.status_code == 202, response.text
        identity = response.json()["id"]
        assert (
            client.post("/api/v1/boss/start", headers=auth, json=body).json()["id"]
            == identity
        )
        assert test_training.wait_run(auth, identity).json()["status"] == "completed"
        answer(auth, identity, config)
        assert wait_submission(auth, identity)["awarded_points"] == 10
        assert wait_evaluation(auth, identity)["status"] == "completed"
        result = client.get(f"/api/v1/boss/tasks/{identity}", headers=auth).json()
        assert result["launch_level"] == result["current_level"] == "初级程序员"
        assert result["disposition"] == "revalidated" and result["promotion_id"] is None
        assert result["decision"]["outcome"] == "independent_pass_candidate"
        assert result["revalidation"]["status"] == "resolved"
        assert [e["kind"] for e in result["revalidation"]["events"]] == [
            "required",
            "resolved",
        ]
        replay(owner, identity)
        review_start(auth, identity, config)
        reviewed = wait_review(auth, identity)
        assert reviewed["decision"] == "corrected", reviewed
        state = access(auth)
        again = state["revalidations"][0]
        assert again["status"] == "required" and state["level"] == "初级程序员"
        assert [e["kind"] for e in again["events"]] == [
            "required",
            "resolved",
            "required",
        ]
        assert again["events"][-1]["review_run_id"] == identity
        replay(owner, identity)
        replay(owner, original)
        assert access(auth)["revalidations"][0] == again
        assert (
            client.post(
                "/api/v1/boss/start",
                headers=auth,
                json=body | {"request_id": str(uuid.uuid4())},
            ).status_code
            == 409
        )

        def third_candidate(payload):
            result = boss_scenarios.candidate(payload, 1)
            if "comparisons" in result:
                return result
            raw = json.dumps(result, ensure_ascii=False)
            for before, after in (
                ("tls_failed", "tcp_refused"),
                ("核对证书与TLS记录", "核对目标端口监听与连接拒绝记录"),
                ("older_session_overwrite", "optimistic_failure_not_rolled_back"),
                ("按会话归属拒绝旧回包", "失败回包后撤销未获确认的乐观状态"),
                ("database_not_checked", "transaction_commit_not_checked"),
                ("核对数据库记录与新会话读取", "核对事务提交与回滚后的持久结果"),
            ):
                raw = raw.replace(before, after)
            return json.loads(raw)

        provider["candidate"] = third_candidate
        response = boss_start(
            auth,
            config,
            revalidation_of=again["promotion_id"],
            expected_revalidation_event_id=again["current_event_id"],
        )
        assert response.status_code == 202, response.text
        newest = response.json()["id"]
        assert test_training.wait_run(auth, newest).json()["status"] == "completed"
        answer(auth, newest, config)
        assert wait_submission(auth, newest)["awarded_points"] == 10
        assert wait_evaluation(auth, newest)["status"] == "completed"
        final = access(auth)["revalidations"][0]
        assert final["status"] == "resolved" and len(final["events"]) == 4
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda _: replay(owner, newest), range(3)))
        with Session(engine) as session:
            lock_owner(session, owner)
            for old in (original, identity):
                old_id = uuid.UUID(old)
                mark_reviewed_promotion(
                    session,
                    session.get(TrainingRun, old_id),
                    session.get(ScoreReview, old_id),
                )
            session.commit()
        assert access(auth)["revalidations"][0] == final
        with Session(engine) as session:
            attempt = session.get(BossAttempt, uuid.UUID(identity))
            assert attempt.launch_level == "初级程序员"
            assert session.get(User, owner).level == "初级程序员"
            assert (
                len(
                    session.exec(
                        select(BossPromotion).where(BossPromotion.user_id == owner)
                    ).all()
                )
                == 1
            )
            assert (
                len(
                    session.exec(
                        select(BossRevalidation).where(
                            BossRevalidation.promotion_id
                            == uuid.UUID(promoted["promotion_id"])
                        )
                    ).all()
                )
                == 4
            )
    finally:
        options(control, review_before_settle=False)
        test_training.stop_worker(process)


@pytest.mark.parametrize("corrected_pass", [False, True])
def test_multiple_requirements_do_not_retroactively_promote_old_round(
    tmp_path, provider, monkeypatch, corrected_pass
):
    from app.training.boss_stages import STAGES
    from tests import stage_scenarios
    from tests.test_boss_stages import SITUATIONS

    owner, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    seed_points(owner, config, 700)
    provider.update(
        candidate=boss_scenarios.candidate,
        grading=boss_scenarios.grade,
        review=corrected,
        source_text=boss_scenarios.REFERENCE,
    )
    first = boss_start(auth, config).json()["id"]
    process, _ = test_training.start_worker(tmp_path, provider, first)

    def ready(identity):
        state = test_training.wait_run(auth, identity).json()
        assert state["status"] == "completed", state

    def finish(identity, stage):
        response = client.post(
            f"/api/v1/training/tasks/{identity}/submissions",
            headers=auth,
            json={
                **consent(config),
                "request_id": str(uuid.uuid4()),
                "evaluate_after_submit": True,
                "answers": [
                    {
                        "judgment_id": m.judgment_id,
                        "value": 0,
                        "reason": "依据各项材料中的实际观察判断，核对风险与持久结果。",
                    }
                    for m in stage.mandatory
                ],
            },
        )
        assert response.status_code == 202, response.text
        assert wait_submission(auth, identity)["awarded_points"] == 10
        assert wait_evaluation(auth, identity)["status"] == "completed"
        return client.get(f"/api/v1/boss/tasks/{identity}", headers=auth).json()

    def open_stage(stage, requirement=None):
        extra = {}
        if requirement:
            extra = {
                "revalidation_of": requirement["promotion_id"],
                "expected_revalidation_event_id": requirement["current_event_id"],
            }
        response = boss_start(
            auth, config, expected_stage=stage.model_dump(mode="json"), **extra
        )
        assert response.status_code == 202, response.text
        identity = response.json()["id"]
        ready(identity)
        return identity

    def stage_review(context):
        result = stage_scenarios.grade(context)
        result["items"][0].update(
            conclusion="evidenced_fail",
            interpreted_reasoning=1,
            gap="该理由忽略了材料中的关键边界",
            counterexample_quote=context["task"]["rubric"][0]["counterexample"],
        )
        return {
            "decision": "corrected",
            "explanation": "核对原冻结理由和反例",
            "grading": result,
        }

    try:
        ready(first)
        assert finish(first, FIRST_STAGE)["current_level"] == "初级程序员"
        provider.update(
            candidate=stage_scenarios.candidate,
            grading=stage_scenarios.grade,
            source_text=stage_scenarios.REFERENCE,
        )
        second = open_stage(STAGES[0])
        assert finish(second, STAGES[0])["current_level"] == "中级程序员"
        # Accepted before either correction, settled after both. Its own frozen
        # disposition must survive future relief and replayed grading callbacks.
        old = open_stage(STAGES[1])
        provider["review"] = corrected
        review_start(auth, first, config)
        assert wait_review(auth, first)["decision"] == "corrected"
        provider["review"] = stage_review
        review_start(auth, second, config)
        assert wait_review(auth, second)["decision"] == "corrected"
        pending = access(auth)["revalidations"]
        assert len(pending) == 2 and all(p["status"] == "required" for p in pending)
        for judgment, rows in {
            "concurrency": (
                "旧事务重放覆盖了新版本记录",
                "用版本条件保护写入并拒绝旧版本重放",
                ["版本2已提交；旧事务仍按版本1无条件覆盖"],
            ),
            "authorization": (
                "同一账号切换租户后带入旧租户订单",
                "读取需核当前租户与订单归属一致",
                ["当前租户B；订单归租户A；查询只按订单ID"],
            ),
            "recovery": (
                "唯一备份校验损坏，旧镜像仍能启动",
                "启动旧镜像不能保证恢复损坏数据，须先核可用恢复证据",
                ["备份校验失败；数据已损坏；旧镜像能启动但无可读副本"],
            ),
            "verify": (
                "首页返回缓存成功但源数据库写入失败",
                "验证须绕过缓存核真实写入与新读取",
                ["缓存首页200；数据库写入失败；持久重读未核对"],
            ),
        }.items():
            monkeypatch.setitem(SITUATIONS, (700, judgment), rows)
        during = open_stage(STAGES[1])
        with Session(engine) as session:
            assert session.get(BossAttempt, uuid.UUID(during)).promotion_blocked
        result = finish(old, STAGES[1])
        assert result["disposition"] == "blocked_revalidation"
        assert result["decision"]["outcome"] == "independent_pass_candidate"
        assert result["decision"]["promote_to"] is None
        assert result["current_level"] == "中级程序员"
        first_pending = next(p for p in pending if p["original_run_id"] == first)
        provider.update(
            candidate=lambda payload: boss_scenarios.candidate(payload, 1),
            grading=boss_scenarios.grade,
            source_text=boss_scenarios.REFERENCE,
        )
        replacement = open_stage(FIRST_STAGE, first_pending)
        if corrected_pass:
            provider["grading"] = lambda context: corrected(context)["grading"]
        result = finish(replacement, FIRST_STAGE)
        if corrected_pass:
            assert result["decision"]["outcome"] == "evidenced_fail"
            provider["review"] = lambda context: {
                "decision": "corrected",
                "explanation": "原判误读冻结理由",
                "grading": boss_scenarios.grade(context),
            }
            review_start(auth, replacement, config)
            assert wait_review(auth, replacement)["decision"] == "corrected"
            result = client.get(
                f"/api/v1/boss/tasks/{replacement}", headers=auth
            ).json()
        assert (
            result["launch_level"] == "中级程序员"
            and result["disposition"] == "revalidated"
        )
        assert (
            sum(p["status"] == "required" for p in access(auth)["revalidations"]) == 1
        )
        replay(owner, old)
        assert access(auth)["level"] == "中级程序员"
        # The next same-stage case changes the observed failure and required
        # action, rather than renaming IDs or adding a hash nonce.
        alternatives = {
            "boundary": (
                "计费模块扣款完成但发货模块尚未收到消息",
                "扣款归计费模块，应核可靠消息投递而非再次扣款",
                ["计费已持久扣款；发货只消费扣款消息；消息尚未投递"],
            ),
            "consistency": (
                "重试同一付款请求产生两个扣款记录",
                "重试需要持久请求身份约束而非读后检查余额",
                ["相同付款身份重试两次；两条扣款均已提交"],
            ),
            "locate": (
                "DNS解析成功但TCP连接被拒绝",
                "应核目标端口监听和连接拒绝记录而非证书",
                ["DNS返回地址；TCP收到拒绝；TLS尚未开始"],
            ),
        }
        for judgment, rows in alternatives.items():
            monkeypatch.setitem(SITUATIONS, (300, judgment), rows)
        provider.update(
            candidate=stage_scenarios.candidate,
            grading=stage_scenarios.grade,
            source_text=stage_scenarios.REFERENCE,
        )
        second_pending = next(p for p in pending if p["original_run_id"] == second)
        replacement2 = open_stage(STAGES[0], second_pending)
        assert finish(replacement2, STAGES[0])["disposition"] == "revalidated"
        assert all(p["status"] == "resolved" for p in access(auth)["revalidations"])
        replay(owner, old)
        result = client.get(f"/api/v1/boss/tasks/{old}", headers=auth).json()
        assert (
            result["disposition"] == "blocked_revalidation"
            and result["promotion_id"] is None
        )
        assert (
            result["current_level"] == "中级程序员"
            and result["decision"]["promote_to"] is None
        )
        result = finish(during, STAGES[1])
        assert result["disposition"] == "blocked_revalidation"
        assert (
            result["promotion_id"] is None and result["current_level"] == "中级程序员"
        )
        # Clearing the last requirement permits only a genuinely new explicit
        # challenge to advance, not either of the two older acceptance windows.
        for judgment, rows in {
            "concurrency": (
                "两事务相反顺序拿锁形成死锁",
                "统一获取顺序并有界重试受影响事务",
                ["A持订单锁等库存锁；B持库存锁等订单锁"],
            ),
            "authorization": (
                "权限已撤销但旧会话仍提交管理操作",
                "服务端操作前应核当前权限和撤销状态",
                ["管理员权限已撤销；旧会话仍持登录凭据；写入未重新核权"],
            ),
            "recovery": (
                "数据库回滚后外部扣款仍成功",
                "本地回滚不能撤销外部扣款，应核对并幂等补偿",
                ["本地事务回滚；外部扣款已确认；没有补偿记录"],
            ),
            "verify": (
                "重试错误响应后形成两条持久记录",
                "验证要覆盖失响应重试并确认同身份仅一条持久记录",
                ["首次提交已持久但响应丢失；重试再插入；现有两条业务记录"],
            ),
        }.items():
            monkeypatch.setitem(SITUATIONS, (700, judgment), rows)
        fresh = open_stage(STAGES[1])
        result = finish(fresh, STAGES[1])
        assert result["promotion_id"] and result["current_level"] == "高级程序员"
        with Session(engine) as session:
            assert not session.get(BossAttempt, uuid.UUID(fresh)).promotion_blocked
            assert (
                len(
                    session.exec(
                        select(BossPromotion).where(BossPromotion.user_id == owner)
                    ).all()
                )
                == 3
            )
    finally:
        test_training.stop_worker(process)


@pytest.mark.parametrize("problem", ["wrong", "help", "late_receipt"])
def test_revalidation_failure_or_help_never_clears_requirement(
    tmp_path, provider, problem
):
    from tests.test_concepts import receipt
    from tests.test_independent_api import confirmed_publication
    from tests.test_practices import guided_coach

    owner, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    seed_points(owner, config, 100)
    provider.update(
        candidate=boss_scenarios.candidate,
        grading=boss_scenarios.grade,
        review=corrected,
        source_text=boss_scenarios.REFERENCE,
        coach=guided_coach,
    )
    original = boss_start(auth, config).json()["id"]
    process, _ = test_training.start_worker(tmp_path, provider, original)
    try:
        assert test_training.wait_run(auth, original).json()["status"] == "completed"
        answer(auth, original, config)
        assert wait_submission(auth, original)["awarded_points"] == 10
        assert wait_evaluation(auth, original)["status"] == "completed"
        review_start(auth, original, config)
        assert wait_review(auth, original)["decision"] == "corrected"
        pending = access(auth)["revalidations"][0]
        provider["candidate"] = lambda payload: boss_scenarios.candidate(payload, 1)
        response = boss_start(
            auth,
            config,
            revalidation_of=pending["promotion_id"],
            expected_revalidation_event_id=pending["current_event_id"],
        )
        assert response.status_code == 202, response.text
        identity = response.json()["id"]
        assert test_training.wait_run(auth, identity).json()["status"] == "completed"
        if problem != "wrong":
            publication = confirmed_publication((auth, identity, config))
            if problem == "help":
                assert receipt(auth, identity, publication).status_code == 200
        answer(auth, identity, config, wrong=problem == "wrong")
        assert wait_submission(auth, identity)["awarded_points"] == 10
        assert wait_evaluation(auth, identity)["status"] == "completed"
        result = client.get(f"/api/v1/boss/tasks/{identity}", headers=auth).json()
        assert (
            result["decision"]["outcome"]
            == {
                "wrong": "evidenced_fail",
                "help": "practice",
                "late_receipt": "pending_delivery",
            }[problem]
        )
        assert result["disposition"] is None
        assert access(auth)["revalidations"][0] == pending
        calls = len(provider["requests"])
        assert (
            client.delete(
                "/api/v1/model-config",
                headers=auth,
                params={"expected_version": config["version"]},
            ).status_code
            == 204
        )
        if problem == "late_receipt":
            assert receipt(auth, identity, publication).status_code == 200
        replay(owner, identity)
        state = access(auth)
        assert state["revalidations"][0] == pending
        assert state["level"] == "初级程序员" and state["points"] == 120
        assert len(provider["requests"]) == calls
        assert (
            boss_start(
                auth,
                config,
                revalidation_of=pending["promotion_id"],
                expected_revalidation_event_id=pending["current_event_id"],
            ).status_code
            == 409
        )
    finally:
        test_training.stop_worker(process)


@pytest.mark.parametrize("decision", ["upheld", "disputed", "authentication"])
def test_only_confirmed_misjudgment_marks_promotion(tmp_path, provider, decision):
    owner, auth = account()
    config = save(auth, service_url=provider["url"]).json()
    seed_points(owner, config, 100)

    def review(context):
        return {
            "decision": decision,
            "explanation": "仅核对冻结原答和原材料",
            "grading": None
            if decision == "disputed"
            else boss_scenarios.grade(context),
        }

    provider.update(
        candidate=boss_scenarios.candidate,
        grading=boss_scenarios.grade,
        review=review,
        source_text=boss_scenarios.REFERENCE,
    )
    identity = boss_start(auth, config).json()["id"]
    process, _ = test_training.start_worker(tmp_path, provider, identity)
    try:
        assert test_training.wait_run(auth, identity).json()["status"] == "completed"
        answer(auth, identity, config)
        assert wait_submission(auth, identity)["awarded_points"] == 10
        assert wait_evaluation(auth, identity)["status"] == "completed"
        if decision == "authentication":
            provider["mode"] = "auth"
        review_start(auth, identity, config)
        result = wait_review(auth, identity)
        assert result["decision"] == (
            "pending" if decision == "authentication" else decision
        )
        replay(owner, identity)
        state = access(auth)
        assert state["revalidations"] == []
        assert state["level"] == "初级程序员" and state["points"] == 110
        with Session(engine) as session:
            assert (
                len(
                    session.exec(
                        select(BossPromotion).where(BossPromotion.user_id == owner)
                    ).all()
                )
                == 1
            )
    finally:
        test_training.stop_worker(process)
