"""预览片构建器的单元 + 集成测试（S12 提交 4）。

覆盖验收：
1. **零付费**：预览全程不产生任何 job、不落 `cost_approvals`、视频方案状态不变（6 个付费入口的等价证据）；
2. 产出物：480×854、时长差 ≤0.5s、≤3MB、可被 ffmpeg 读出尺寸与时长；
3. **不入交付物**：`outputs` 表无新行、交付门结论不变、`final.mp4` key 未被占用；
4. 幂等：连续两次只渲染一次（第二次 `cached=True`，产物字节不变）；
5. 出片速度：≤60 秒。
"""
from __future__ import annotations

import time
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

import pytest
from onetake_api.config import get_settings
from onetake_api.integrations.media.video_utils import inspect_video_dimensions, inspect_video_duration
from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.modules.asset.adapters.sqlalchemy_repository import SqlAlchemyAssetRepository
from onetake_api.modules.asset.domain.model import ASSET_STATUS_READY, create_pending_asset
from onetake_api.modules.content_plan.public import ContentPlanPublicService
from onetake_api.modules.job.repository import JobModel
from onetake_api.modules.output.repository import OutputArtifactModel
from onetake_api.modules.pipeline.orchestrator import PipelineOrchestrator
from onetake_api.modules.pipeline.public import PipelinePublicService
from onetake_api.modules.preview.domain import (
    BASE_SOURCE_MOCK,
    PREVIEW_HEIGHT,
    PREVIEW_MAX_BYTES,
    PREVIEW_WIDTH,
    preview_key,
)
from onetake_api.modules.preview.service import PreviewService
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.modules.video_plan.public import VideoPlanPublicService
from onetake_api.platform.clock import SystemClock


class FakeQueue:
    def enqueue(self, *_args, **_kwargs):
        return None


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


def _build_project_with_plan(session: Session, storage: ObjectStoragePublicService, monkeypatch, name: str):
    _patch_queues(monkeypatch)
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
    plan = VideoPlanPublicService().create_plan(
        session, project_id=project.id, mode="product", template_id="clean", path="segmented"
    ).plan
    return project, plan


def _job_count(session: Session, project_id: str) -> int:
    return len(session.scalars(select(JobModel).where(JobModel.project_id == project_id)).all())


def test_preview_is_free_and_meets_spec(db_session: Session, object_storage, monkeypatch) -> None:
    project, plan = _build_project_with_plan(db_session, object_storage, monkeypatch, "预览")
    service = PreviewService(storage=object_storage)
    jobs_before = _job_count(db_session, project.id)
    outputs_before = len(db_session.scalars(select(OutputArtifactModel).where(OutputArtifactModel.project_id == project.id)).all())
    approvals_before = PipelinePublicService().list_cost_approvals(db_session, project.id)

    started = time.monotonic()
    artifact = service.build_preview(db_session, project.id)
    elapsed = time.monotonic() - started

    # 验收 1：零付费（不产生任何 job → 6 个付费入口一个都没进）
    assert _job_count(db_session, project.id) == jobs_before, "预览不得产生任何 job"
    assert PipelinePublicService().list_cost_approvals(db_session, project.id) == approvals_before
    assert VideoPlanPublicService().latest(db_session, project.id).plan.status == "plan_ready"

    # 验收 2：规格
    assert (artifact.width, artifact.height) == (PREVIEW_WIDTH, PREVIEW_HEIGHT) == (480, 854)
    assert abs(artifact.duration_seconds - plan.duration_seconds) <= 0.5
    assert artifact.size_bytes <= PREVIEW_MAX_BYTES, artifact.size_bytes
    content = b"".join(object_storage.read_object(object_key=artifact.object_key))
    assert inspect_video_dimensions(content) == (PREVIEW_WIDTH, PREVIEW_HEIGHT)
    assert abs(inspect_video_duration(content) - plan.duration_seconds) <= 0.5
    assert artifact.base_source == BASE_SOURCE_MOCK
    assert artifact.object_key == preview_key(project.id, plan.id)

    # 验收 3：不入交付物
    assert len(db_session.scalars(select(OutputArtifactModel).where(OutputArtifactModel.project_id == project.id)).all()) == outputs_before
    assert artifact.object_key != f"projects/{project.id}/output/{plan.id}/final.mp4"

    # 验收 5：出片速度
    assert elapsed <= 60, elapsed


def test_preview_is_idempotent(db_session: Session, object_storage, monkeypatch) -> None:
    project, plan = _build_project_with_plan(db_session, object_storage, monkeypatch, "预览幂等")
    service = PreviewService(storage=object_storage)

    first = service.build_preview(db_session, project.id)
    started = time.monotonic()
    second = service.build_preview(db_session, project.id)
    elapsed = time.monotonic() - started

    assert first.cached is False
    assert second.cached is True, "第二次必须命中缓存"
    assert second.fingerprint == first.fingerprint
    assert second.size_bytes == first.size_bytes
    assert elapsed <= 5, f"命中缓存不该重新渲染（{elapsed:.2f}s）"


def test_preview_fingerprint_changes_when_plan_changes(db_session: Session, object_storage, monkeypatch) -> None:
    project, plan = _build_project_with_plan(db_session, object_storage, monkeypatch, "预览指纹")
    service = PreviewService(storage=object_storage)
    first = service.build_preview(db_session, project.id)

    # 换一份新方案（新 plan_id）→ 指纹变 → 不复用旧预览
    second_plan = VideoPlanPublicService().create_plan(
        db_session, project_id=project.id, mode="product", template_id="clean", path="segmented"
    ).plan
    assert second_plan.id != plan.id
    rebuilt = service.build_preview(db_session, project.id)
    assert rebuilt.plan_id == second_plan.id
    assert rebuilt.cached is False
    assert rebuilt.fingerprint != first.fingerprint

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
