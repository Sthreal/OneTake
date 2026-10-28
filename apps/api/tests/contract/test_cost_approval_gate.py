"""付费入口的费用审批契约（S8 硬约束）。

对应 S8+S9+S10 验收 1 / 2：不写审批记录时 6 个付费入口全部 4xx 且**零适配器调用**；
改配置后（payload_hash 变化）旧审批自动失效。
"""
from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

import pytest
from onetake_api.config import Settings, get_settings
from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.modules.asset.adapters.sqlalchemy_repository import SqlAlchemyAssetRepository
from onetake_api.modules.asset.domain.model import ASSET_STATUS_READY, create_pending_asset
from onetake_api.modules.content_plan.public import ContentPlanPublicService
from onetake_api.modules.job.repository import JobModel
from onetake_api.modules.pipeline.orchestrator import PipelineOrchestrator
from onetake_api.modules.pipeline.public import PipelinePublicService
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.modules.video_plan.public import VideoPlanPublicService
from onetake_api.modules.video_plan.segment_public import VideoSegmentPublicService
from onetake_api.modules.video_plan.service import VideoPlanApplicationService


class FakeQueue:
    def enqueue(self, *_args, **_kwargs):
        return None


class _StubComposition:
    provider_name = "shotstack"


class _CountingGenerator:
    calls = 0

    def __init__(self, *args, **kwargs):
        type(self).calls += 1


def _patch_queues(monkeypatch) -> None:
    for module in (
        "onetake_api.modules.recognition.service",
        "onetake_api.modules.main_image.service",
        "onetake_api.modules.script.service",
        "onetake_api.modules.voice.service",
        "onetake_api.modules.subtitle.api",
        "onetake_api.modules.video_plan.service",
    ):
        monkeypatch.setattr(f"{module}.get_queue", lambda _name: FakeQueue())


def _product_png() -> bytes:
    image = Image.new("RGB", (900, 900), (255, 255, 255))
    product = Image.new("RGB", (360, 520), (235, 78, 54))
    image.paste(product, (270, 190))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _build_project(session: Session, storage, monkeypatch, name: str):
    _patch_queues(monkeypatch)
    # 本用例用自动链搭出「已确认分镜 + 视频方案」的前置状态
    monkeypatch.setenv("AUTO_RUN_ENABLED", "true")
    get_settings.cache_clear()
    project = ProjectPublicService().create_project(session, product_name=name, product_note="轻便好用的随身水杯")
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

    PipelineOrchestrator().resume_from_stage(session, project.id, "recognition")
    ContentPlanPublicService().generate(session, project.id)
    ContentPlanPublicService().confirm(session, project.id)
    view = VideoPlanPublicService().create_plan(
        session, project_id=project.id, mode="product", template_id="clean", path="segmented"
    )
    return project, view.plan


def _job_count(session: Session, project_id: str) -> int:
    return len(session.scalars(select(JobModel).where(JobModel.project_id == project_id)).all())


def test_paid_endpoints_require_cost_approval(client, db_session, object_storage, monkeypatch) -> None:
    project, plan = _build_project(db_session, object_storage, monkeypatch, "付费闸")
    # 本用例钉费用闸。审稿闸默认 enforce 会先返回 SCRIPT_REVIEW_REQUIRED。
    monkeypatch.setenv("SCRIPT_REVIEW_GATE", "off")
    get_settings.cache_clear()
    segments = VideoSegmentPublicService().materialize_segments(db_session, project_id=project.id)
    assert segments, "需要至少一个分段用于返修/候选入口"
    segment_id = segments[0].id

    # 把「当前配置」切到会真花钱的样子（预估 1.00 元），并挡掉真实 Shotstack 构造
    paid = Settings(mock_providers=False, composition_provider="shotstack",
                    shotstack_render_price=1.0, wan_i2v_provider="mock")
    monkeypatch.setattr("onetake_api.modules.video_plan.service.get_settings", lambda: paid)
    monkeypatch.setattr("onetake_api.modules.video_plan.service.get_composition_provider", lambda: _StubComposition())
    _CountingGenerator.calls = 0
    monkeypatch.setattr("onetake_api.modules.video_plan.segment_service.SegmentVideoGenerator", _CountingGenerator)
    monkeypatch.setattr("onetake_api.modules.video_plan.keyframe_service.KeyframeGenerator", _CountingGenerator)

    pid = project.id
    jobs_before = _job_count(db_session, pid)
    paid_calls = [
        ("POST", f"/api/v1/projects/{pid}/video", None),
        ("POST", f"/api/v1/projects/{pid}/compose", None),
        ("POST", f"/api/v1/projects/{pid}/video/batch", None),
        ("POST", f"/api/v1/projects/{pid}/video/segments/{segment_id}/candidates", {}),
        ("POST", f"/api/v1/projects/{pid}/video/segments/{segment_id}/retake", {"symptom": "blurry"}),
        ("POST", f"/api/v1/projects/{pid}/video/keyframes/scene_1/candidates", {"mode": "integrated", "n": 1}),
    ]
    for method, url, body in paid_calls:
        response = client.request(method, url, json=body)
        assert response.status_code == 409, (url, response.status_code, response.text)
        assert response.json()["error"]["code"] == "COST_APPROVAL_REQUIRED", (url, response.text)

    assert _job_count(db_session, pid) == jobs_before, "被拒的调用不得创建任何 job"
    assert _CountingGenerator.calls == 0, "被拒的调用不得进入任何生成适配器"
    refreshed = VideoPlanPublicService().latest(db_session, pid)
    assert refreshed.plan.status == "plan_ready", refreshed.plan.status
    assert PipelinePublicService().list_cost_approvals(db_session, pid) == []

    # 批准当前这份预估 → 闸门打开
    context = VideoPlanApplicationService().approve_cost(
        db_session, project_id=pid, plan_id=plan.id, approved_by="tester"
    )
    db_session.commit()
    assert context.is_paid is True and context.estimated_cny == 1.0
    opened = client.post(f"/api/v1/projects/{pid}/video")
    assert opened.status_code == 202, opened.text

    # 改配置 → 预估变化 → payload_hash 变化 → 旧审批自动失效
    monkeypatch.undo()
    _patch_queues(monkeypatch)
    paid2 = Settings(mock_providers=False, composition_provider="shotstack",
                     shotstack_render_price=2.0, wan_i2v_provider="mock")
    monkeypatch.setattr("onetake_api.modules.video_plan.service.get_settings", lambda: paid2)
    monkeypatch.setattr("onetake_api.modules.video_plan.service.get_composition_provider", lambda: _StubComposition())
    stale = client.post(f"/api/v1/projects/{pid}/compose")
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"]["code"] == "COST_APPROVAL_REQUIRED"

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
