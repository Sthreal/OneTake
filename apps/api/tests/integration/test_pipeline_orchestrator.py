"""流水线推进器的集成验收（S8 + S9 + S10）。

覆盖验收：
- 3  自动段能跑通：识别 → 主图 → 文案 → 配音字幕 在**人工闸口①**停下，
     `auto_confirmed_stages` 记 4 段、outbox 有 4 条 `GateAutoConfirmed`；
- 4  断点续跑：进程死过一次的 run 被标 `interrupted`，从断点继续且**不重复计费**；
- 5  并发不双写：同项目第二次进入被拒，且 `state_version` 不跳变；
- 6  预算截停：预算不足以进视频块 → 停在阶段边界、标 `require_human`、零供应商调用；
- 7  `MOCK_PROVIDERS=true` 下自动链只跑 mock，不产生任何 `cost_approvals` 行。
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from onetake_api.config import Settings, get_settings
from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.modules.asset.adapters.sqlalchemy_repository import SqlAlchemyAssetRepository
from onetake_api.modules.asset.domain.model import ASSET_STATUS_READY, create_pending_asset
from onetake_api.modules.content_plan.public import ContentPlanPublicService
from onetake_api.modules.job.repository import JobModel
from onetake_api.modules.outbox.adapters.sqlalchemy_repository import OutboxEventModel
from onetake_api.modules.pipeline.orchestrator import (
    RUNNING_RUNS,
    AutoRunDisabledError,
    PipelineConflictError,
    PipelineOrchestrator,
)
from onetake_api.modules.pipeline.public import PipelinePublicService
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.modules.recognition.service import RecognitionService
from onetake_api.modules.script.public import ScriptPublicService
from onetake_api.modules.video_plan.public import VideoPlanPublicService
from onetake_api.modules.voice.public import VoicePublicService
from onetake_api.platform.errors import DomainError


class FakeQueue:
    def enqueue(self, *_args, **_kwargs):
        return None


class _StubComposition:
    provider_name = "shotstack"


# 自动链经过的模块（全部换成假队列：集成测试自己驱动 job，不依赖 rq worker）
_QUEUE_MODULES = (
    "onetake_api.modules.recognition.service",
    "onetake_api.modules.main_image.service",
    "onetake_api.modules.script.service",
    "onetake_api.modules.voice.service",
    "onetake_api.modules.subtitle.api",
    "onetake_api.modules.video_plan.service",
)


def _patch_queues(monkeypatch) -> None:
    for module in _QUEUE_MODULES:
        monkeypatch.setattr(f"{module}.get_queue", lambda _name: FakeQueue())


def _enable_auto_run(monkeypatch, *, budget: str = "0") -> None:
    monkeypatch.setenv("AUTO_RUN_ENABLED", "true")
    monkeypatch.setenv("AUTO_RUN_BUDGET_CNY", budget)
    get_settings.cache_clear()


def _product_png() -> bytes:
    image = Image.new("RGB", (900, 900), (255, 255, 255))
    product = Image.new("RGB", (360, 520), (235, 78, 54))
    image.paste(product, (270, 190))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _build_project(session: Session, storage: ObjectStoragePublicService, monkeypatch, name: str):
    _patch_queues(monkeypatch)
    project = ProjectPublicService().create_project(
        session, product_name=name, product_note="轻便好用的随身水杯"
    )
    content = _product_png()
    now = datetime.now(UTC)
    asset = create_pending_asset(
        asset_id=f"ast_{project.id}",
        project_id=project.id,
        object_key=f"projects/{project.id}/assets/ast/original.png",
        original_filename="商品.png",
        mime_type="image/png",
        size_bytes=len(content),
        width=900,
        height=900,
        sha256=sha256(content).hexdigest(),
        now=now,
    )
    asset = asset.__class__(**{**asset.__dict__, "status": ASSET_STATUS_READY})
    SqlAlchemyAssetRepository().add(session, asset)
    storage.put_bytes(object_key=asset.object_key, content=content, mime_type="image/png")
    session.flush()
    return project


def _gate_auto_confirmed(session: Session, *, run_id: str) -> list[str]:
    """本 run 的 GateAutoConfirmed 事件（**必须按 run 过滤**）。

    为什么不查全局：这些用例跑在**共用的开发库**上，库里可能有其它来源已提交的事件
    （例如容器里的端到端探针）—— 断言全局状态会随"库里还有什么"而假红。
    本切片就踩过一次：容器探针留下 3 条事件 → 这里的计数从 4 变成 7。
    """
    events = session.scalars(
        select(OutboxEventModel).where(
            OutboxEventModel.event_name == "GateAutoConfirmed",
            OutboxEventModel.aggregate_id == run_id,
        )
    ).all()
    return [event.payload["stage"] for event in events]


def _job_count(session: Session, project_id: str) -> int:
    return len(session.scalars(select(JobModel).where(JobModel.project_id == project_id)).all())


def test_auto_chain_runs_free_stages_and_stops_at_gate_one(
    db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    _enable_auto_run(monkeypatch)
    project = _build_project(db_session, object_storage, monkeypatch, "自动链")

    result = PipelineOrchestrator().resume_from_stage(db_session, project.id, "recognition")

    assert result.auto_confirmed == ["recognition", "main_image", "script", "voice_subtitle"], result
    assert result.stopped_at == "content_plan"
    assert result.stopped_reason == "human_gate"
    run = PipelinePublicService().get_or_create(db_session, project.id)
    assert run.status == "audio_subtitle_confirmed"
    assert run.auto_run is True
    assert run.auto_confirmed_stages == result.auto_confirmed
    assert run.stage == "content_plan"
    assert _gate_auto_confirmed(db_session, run_id=run.id) == result.auto_confirmed
    assert RUNNING_RUNS == set()


def test_second_run_does_not_re_bill(
    db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    """验收 4 的「不重复计费」：同一段已就绪时只重放自动确认，不再触发一次请求。"""
    _enable_auto_run(monkeypatch)
    project = _build_project(db_session, object_storage, monkeypatch, "幂等链")

    PipelineOrchestrator().resume_from_stage(db_session, project.id, "recognition")
    jobs_after_first = _job_count(db_session, project.id)

    again = PipelineOrchestrator().resume_from_stage(db_session, project.id, "recognition")

    assert again.auto_confirmed == [], again
    assert again.stopped_at == "content_plan"
    assert _job_count(db_session, project.id) == jobs_after_first, "续跑不得再创建 job"
    run = PipelinePublicService().get_or_create(db_session, project.id)
    assert len(_gate_auto_confirmed(db_session, run_id=run.id)) == 4, "不得重复落 GateAutoConfirmed"


def test_detect_orphans_then_resume_from_breakpoint(
    db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    """验收 4 的断点语义：进程死过一次 → 标 interrupted → 从断点继续且不重复计费。"""
    _enable_auto_run(monkeypatch)
    project = _build_project(db_session, object_storage, monkeypatch, "孤儿链")
    orchestrator = PipelineOrchestrator()
    orchestrator.resume_from_stage(db_session, project.id, "recognition")
    jobs_before = _job_count(db_session, project.id)

    # 模拟「自动链跑到 voice_subtitle 时进程被杀」：DB 里留着 auto_run、进程注册表里没有
    PipelinePublicService().mark_auto_run(db_session, project.id, stage="voice_subtitle")
    db_session.commit()
    assert RUNNING_RUNS == set()
    orphans = orchestrator.detect_orphans(db_session)
    run = PipelinePublicService().get_or_create(db_session, project.id)
    assert run.id in orphans
    assert run.status == "interrupted", run.status
    # 已终态 → 第二次不再重复标记
    assert orchestrator.detect_orphans(db_session) == []

    resumed = orchestrator.resume_from_stage(db_session, project.id, "voice_subtitle")
    assert resumed.stopped_at == "content_plan", resumed
    assert _job_count(db_session, project.id) == jobs_before, "从断点续跑不得重复计费"


def test_concurrent_run_is_rejected_without_writing(
    db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    """验收 5：同项目已有自动链在跑 → 后者冲突返回，state_version 不跳变。"""
    _enable_auto_run(monkeypatch)
    project = _build_project(db_session, object_storage, monkeypatch, "并发链")
    orchestrator = PipelineOrchestrator()
    run = PipelinePublicService().get_or_create(db_session, project.id)

    RUNNING_RUNS.add(run.id)
    try:
        with pytest.raises(PipelineConflictError):
            orchestrator.resume_from_stage(db_session, project.id, "recognition")
    finally:
        RUNNING_RUNS.discard(run.id)

    after = PipelinePublicService().get_or_create(db_session, project.id)
    assert after.state_version == run.state_version
    assert after.status == run.status
    assert after.auto_run is False
    assert after.stage is None


def test_auto_run_disabled_by_default_is_refused_without_writing(
    db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    monkeypatch.setenv("AUTO_RUN_ENABLED", "false")
    get_settings.cache_clear()
    project = _build_project(db_session, object_storage, monkeypatch, "默认关闭")
    before = PipelinePublicService().get_or_create(db_session, project.id)

    with pytest.raises(AutoRunDisabledError):
        PipelineOrchestrator().resume_from_stage(db_session, project.id, "recognition")

    after = PipelinePublicService().get_or_create(db_session, project.id)
    assert after.state_version == before.state_version
    assert after.auto_run is False


def test_budget_stop_makes_no_provider_call(
    db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    """验收 6：预算进不了视频块 → 停下并标 require_human，零供应商调用。"""
    _enable_auto_run(monkeypatch)
    project = _build_project(db_session, object_storage, monkeypatch, "预算截停")
    orchestrator = PipelineOrchestrator()
    orchestrator.resume_from_stage(db_session, project.id, "recognition")
    ContentPlanPublicService().generate(db_session, project.id)
    ContentPlanPublicService().confirm(db_session, project.id)
    VideoPlanPublicService().create_plan(
        db_session, project_id=project.id, mode="product", template_id="clean", path="segmented"
    )

    # 把配置切成「真的会花钱」（预估 3.00 元），并挡掉真实 Shotstack 适配器构造
    paid = Settings(
        mock_providers=False, composition_provider="shotstack",
        shotstack_render_price=3.0, wan_i2v_provider="mock",
    )
    monkeypatch.setattr("onetake_api.modules.video_plan.service.get_settings", lambda: paid)
    monkeypatch.setattr(
        "onetake_api.modules.video_plan.service.get_composition_provider", lambda: _StubComposition()
    )

    jobs_before = _job_count(db_session, project.id)
    blocked = orchestrator.resume_from_stage(db_session, project.id, "keyframes", budget_cny=0.0)
    assert blocked.stopped_reason == "budget", blocked
    assert blocked.stopped_at == "keyframes", blocked
    assert blocked.required_action == "require_human", blocked
    assert _job_count(db_session, project.id) == jobs_before, "预算截停不得产生任何供应商调用"
    stopped_events = db_session.scalars(
        select(OutboxEventModel).where(OutboxEventModel.event_name == "AutoRunBudgetStopped")
    ).all()
    assert stopped_events and stopped_events[-1].payload["estimated_cny"] == 3.0
    assert stopped_events[-1].payload["action"] == "require_human"

    # 预算够 → 不在预算处停（后面会因为视频块没有自动驱动器而停在别处）
    allowed = orchestrator.resume_from_stage(db_session, project.id, "keyframes", budget_cny=100.0)
    assert allowed.stopped_reason != "budget", allowed


def test_mock_chain_never_writes_cost_approvals(
    db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    """验收 7：MOCK_PROVIDERS=true 下只跑 mock，且不产生任何 cost_approvals 行。"""
    _enable_auto_run(monkeypatch)
    project = _build_project(db_session, object_storage, monkeypatch, "mock 链")
    PipelineOrchestrator().resume_from_stage(db_session, project.id, "recognition")
    assert PipelinePublicService().list_cost_approvals(db_session, project.id) == []


def test_gate_one_passed_lets_chain_continue(
    db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    """闸口① 被人放行后，自动链不再停在那里（但不代按）。"""
    _enable_auto_run(monkeypatch)
    project = _build_project(db_session, object_storage, monkeypatch, "放行闸口")
    orchestrator = PipelineOrchestrator()
    orchestrator.resume_from_stage(db_session, project.id, "recognition")
    ContentPlanPublicService().generate(db_session, project.id)
    ContentPlanPublicService().confirm(db_session, project.id)

    result = orchestrator.resume_from_stage(db_session, project.id, "content_plan")
    assert result.stopped_at == "content_qa", result
    assert result.stopped_reason == "unsupported", result


def test_recover_from_failure_prefers_error_policy_then_stage_default(
    db_session: Session,
) -> None:
    """S10：已登记的错误码按 ERROR_POLICY 分类；未登记的回落到该阶段的默认动作。"""
    project = ProjectPublicService().create_project(db_session, product_name="恢复", product_note=None)
    orchestrator = PipelineOrchestrator()

    class TransientError(DomainError):
        code = "RECOGNITION_PROVIDER_ERROR"

    class PolicyError(DomainError):
        code = "AIGC_LABEL_CHECK_FAILED"

    class BrandNewError(DomainError):
        code = "BRAND_NEW_CODE_NOT_REGISTERED"

    transient = orchestrator.recover_from_failure(db_session, project.id, TransientError("x"), stage="recognition")
    assert (transient.error_class, transient.action) == ("transient", "retry")
    policy = orchestrator.recover_from_failure(db_session, project.id, PolicyError("x"), stage="recognition")
    assert (policy.error_class, policy.action) == ("policy", "require_human")
    # 未登记 + 阶段是 best_effort（content_qa）→ 用阶段默认动作「跳过」
    unknown_qa = orchestrator.recover_from_failure(db_session, project.id, BrandNewError("x"), stage="content_qa")
    assert unknown_qa.action == "skip_stage", unknown_qa
    # 未登记 + 阶段是 fatal（recognition）→ require_human
    unknown_fatal = orchestrator.recover_from_failure(db_session, project.id, BrandNewError("x"), stage="recognition")
    assert unknown_fatal.action == "require_human", unknown_fatal
    # 没给阶段 → 全局最保守默认
    unknown_bare = orchestrator.recover_from_failure(db_session, project.id, BrandNewError("x"))
    assert (unknown_bare.error_class, unknown_bare.action) == ("permanent", "require_human")

@pytest.fixture(autouse=True)
def _declare_no_queue_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """显式声明"队列里没有 worker"（S8+S9+S10 修复后的口径）。

    推进器现在会探测 rq 的 worker 注册表：**有 worker 就不抢活、只等它跑完**（否则两边各调一次供应商
    = 重复付费）。而宿主机 pytest 与容器**共用同一个 redis**，容器里的 worker 会把自己注册进去，
    于是探测结果会是 True —— 这些用例用的是**假队列**（自己驱动 job），所以必须显式声明没有 worker。
    """
    monkeypatch.setattr(
        "onetake_api.modules.pipeline.orchestrator._queue_has_worker", lambda: False
    )


def test_waits_for_external_worker_instead_of_double_processing(
    db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    """有 rq worker 时推进器**不抢活** —— 只等它跑完（缺陷 A 的回归测试）。

    为什么这条最重要：内联处理与 worker 会抢同一个 job，两边**各调一次供应商**
    （真实配置下实测：阿里去背被重复付费调用一次）。
    """
    import onetake_api.modules.pipeline.orchestrator as orchestrator_module

    _enable_auto_run(monkeypatch)
    project = _build_project(db_session, object_storage, monkeypatch, "外部 worker")
    monkeypatch.setattr(orchestrator_module, "_queue_has_worker", lambda: True)
    monkeypatch.setattr(orchestrator_module, "EXTERNAL_WORKER_WAIT_SECONDS", 0.0)  # 不等，直接超时

    processed: list[str] = []
    monkeypatch.setattr(
        RecognitionService,
        "process_job",
        lambda self, session, job_id: processed.append(job_id),
    )

    result = PipelineOrchestrator().resume_from_stage(db_session, project.id, "recognition")

    assert processed == [], "队列里有 worker 时**绝不能**自己处理 job（会与 worker 重复调用供应商）"
    assert result.stopped_at == "recognition", result
    assert result.stopped_reason == "external_worker", result
    assert result.required_action is None


def test_auto_run_voice_id_comes_from_settings(
    db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    """自动链音色取自 `AUTO_RUN_VOICE_ID`（缺陷 B 的回归测试）。

    真实 CosyVoice 的音色 ID 与 mock 不同：硬编码 `longxiaochun`（v1 音色）+ `cosyvoice-v2`
    会被供应商拒掉（实测 418 InvalidParameter），自动链就**必然卡在配音段**。
    """
    _enable_auto_run(monkeypatch)
    project = _build_project(db_session, object_storage, monkeypatch, "音色配置")
    monkeypatch.setenv("AUTO_RUN_VOICE_ID", "longxiaochun_v2")
    get_settings.cache_clear()

    PipelineOrchestrator().resume_from_stage(db_session, project.id, "recognition")

    run = VoicePublicService().latest(db_session, project.id).run
    assert run is not None, "自动链必须真的跑出配音"
    assert run.voice_id == "longxiaochun_v2", run.voice_id


def test_default_auto_run_voice_matches_the_frontend_default() -> None:
    """默认音色必须与活前端配音面板的默认**一致**，且是 v2 音色。

    这条不是"风格偏好"：默认写成 v1 的 `longxiaochun` + `VOICE_MODEL=cosyvoice-v2` 会被供应商拒掉
    （实测 418 InvalidParameter），自动链就**必然卡在配音段**；而前端 VoicePanel.tsx 的 VOICES 一直用的
    是 `longxiaochun_v2`。两边对齐，才不会出现「UI 能用、自动链 418」的错位。
    """
    from onetake_api.config import Settings

    # 断言字段**默认值**（不读环境，避免被 .env / shell 变量影响）
    assert Settings.model_fields["auto_run_voice_id"].default == "longxiaochun_v2"


def test_transient_failure_is_retried_once(db_session: Session, object_storage: ObjectStoragePublicService,
                                           monkeypatch) -> None:
    """失败重试（S10 的"retry"动作终于有人执行）：transient 失败 → 自动重跑；permanent → 交人工、不烧钱。"""
    from onetake_api.modules.script.domain import STATUS_FAILED as SCRIPT_FAILED
    from onetake_api.modules.script.repository import ScriptRepository

    _enable_auto_run(monkeypatch)
    project = _build_project(db_session, object_storage, monkeypatch, "失败重试")

    # 把文案阶段做成"已存在但失败，且错误码是 transient"（真实场景：供应商偶发失败）
    PipelineOrchestrator().resume_from_stage(db_session, project.id, "recognition")
    version = ScriptPublicService().latest(db_session, project.id).version
    assert version is not None
    ScriptRepository().update(
        db_session, replace(version, status=SCRIPT_FAILED, error_code="SCRIPT_PROVIDER_ERROR")
    )
    db_session.commit()
    requests: list[str] = []
    monkeypatch.setattr(
        ScriptPublicService, "request", lambda self, session, **kwargs: requests.append("retry")
    )

    result = PipelineOrchestrator().resume_from_stage(db_session, project.id, "script")

    assert requests == ["retry"], "transient 失败必须被自动重跑**恰好一次**（不能打到步数上限）"
    assert result.stopped_at == "script"
    # 重跑一次后产物仍是失败 → 停手交人工，不再自动花钱
    assert result.stopped_reason == "failed:require_human", result
    assert result.required_action == "require_human", result


def test_permanent_failure_is_handed_to_human_without_retry(
    db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    """永久性失败（例如供应商未配置）**不重跑** —— 真实付费链路上盲目重试就是白花钱。"""
    from onetake_api.modules.script.domain import STATUS_FAILED as SCRIPT_FAILED
    from onetake_api.modules.script.repository import ScriptRepository

    _enable_auto_run(monkeypatch)
    project = _build_project(db_session, object_storage, monkeypatch, "永久失败")

    PipelineOrchestrator().resume_from_stage(db_session, project.id, "recognition")
    version = ScriptPublicService().latest(db_session, project.id).version
    assert version is not None
    ScriptRepository().update(
        db_session,
        replace(version, status=SCRIPT_FAILED, error_code="SCRIPT_PROVIDER_NOT_CONFIGURED"),
    )
    db_session.commit()
    requests: list[str] = []
    monkeypatch.setattr(
        ScriptPublicService, "request", lambda self, session, **kwargs: requests.append("retry")
    )

    result = PipelineOrchestrator().resume_from_stage(db_session, project.id, "script")

    assert requests == [], "永久性失败不得自动重跑"
    assert result.stopped_at == "script"
    assert result.stopped_reason == "failed:require_human"
    assert result.required_action == "require_human"
