"""预览片两个端点的契约（S12 提交 4）。

`POST` 幂等（第二次 `cached=true`）、`GET` 取签名 URL、没有方案时 404、开关关闭时 403。
"""
from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO

from PIL import Image

import pytest
from onetake_api.config import get_settings
from onetake_api.modules.asset.adapters.sqlalchemy_repository import SqlAlchemyAssetRepository
from onetake_api.modules.asset.domain.model import ASSET_STATUS_READY, create_pending_asset
from onetake_api.modules.content_plan.public import ContentPlanPublicService
from onetake_api.modules.pipeline.orchestrator import PipelineOrchestrator
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.modules.video_plan.public import VideoPlanPublicService


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


def _project_with_plan(session, storage, monkeypatch, name: str):
    _patch_queues(monkeypatch)
    monkeypatch.setenv("AUTO_RUN_ENABLED", "true")
    get_settings.cache_clear()
    project = ProjectPublicService().create_project(session, product_name=name, product_note="轻便好用的随身水杯")
    content = _product_png()
    now = datetime.now(UTC)
    asset = create_pending_asset(
        asset_id=f"ast_{project.id}", project_id=project.id,
        object_key=f"projects/{project.id}/assets/ast/original.png", original_filename="商品.png",
        mime_type="image/png", size_bytes=len(content), width=900, height=900,
        sha256=sha256(content).hexdigest(), now=now,
    )
    asset = asset.__class__(**{**asset.__dict__, "status": ASSET_STATUS_READY})
    SqlAlchemyAssetRepository().add(session, asset)
    storage.put_bytes(object_key=asset.object_key, content=content, mime_type="image/png")
    session.flush()
    PipelineOrchestrator().resume_from_stage(session, project.id, "recognition")
    ContentPlanPublicService().generate(session, project.id)
    ContentPlanPublicService().confirm(session, project.id)
    VideoPlanPublicService().create_plan(
        session, project_id=project.id, mode="product", template_id="clean", path="segmented"
    )
    return project.id


def test_preview_endpoints_are_idempotent_and_typed(client, db_session, object_storage, monkeypatch) -> None:
    project_id = _project_with_plan(db_session, object_storage, monkeypatch, "预览契约")

    created = client.post(f"/api/v1/projects/{project_id}/preview")
    assert created.status_code == 200, created.text
    data = created.json()["data"]
    assert set(data) == {
        "plan_id", "video_url", "width", "height", "fps", "duration_seconds",
        "size_bytes", "cached", "base_source", "audio_source",
    }
    assert (data["width"], data["height"]) == (480, 854)
    assert data["cached"] is False
    assert data["video_url"], "必须给出可访问的签名 URL"
    assert data["size_bytes"] <= 3 * 1024 * 1024

    again = client.post(f"/api/v1/projects/{project_id}/preview")
    assert again.status_code == 200, again.text
    assert again.json()["data"]["cached"] is True

    fetched = client.get(f"/api/v1/projects/{project_id}/preview")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["data"]["plan_id"] == data["plan_id"]
    assert fetched.json()["data"]["cached"] is True


def test_preview_get_without_preview_returns_404(client, db_session, object_storage, monkeypatch) -> None:
    project_id = _project_with_plan(db_session, object_storage, monkeypatch, "预览缺失")
    response = client.get(f"/api/v1/projects/{project_id}/preview")
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "PREVIEW_NOT_FOUND"


def test_preview_can_be_disabled_by_config(client, db_session, object_storage, monkeypatch) -> None:
    project_id = _project_with_plan(db_session, object_storage, monkeypatch, "预览关闭")
    monkeypatch.setenv("PREVIEW_ENABLED", "false")
    get_settings.cache_clear()
    response = client.post(f"/api/v1/projects/{project_id}/preview")
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "PREVIEW_DISABLED"

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
