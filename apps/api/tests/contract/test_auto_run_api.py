"""自动链四个 HTTP 端点的契约（S8/S9/S10 提交 7）。

对应验收 3（一键跑完中间段并在闸口① 停）、验收 4 的断点语义、验收 6 的默认关闭。
"""
from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO

from PIL import Image
from sqlalchemy.orm import Session

import pytest
from onetake_api.config import get_settings
from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.modules.asset.adapters.sqlalchemy_repository import SqlAlchemyAssetRepository
from onetake_api.modules.asset.domain.model import ASSET_STATUS_READY, create_pending_asset
from onetake_api.modules.content_plan.public import ContentPlanPublicService
from onetake_api.modules.pipeline.orchestrator import PipelineOrchestrator
from onetake_api.modules.pipeline.public import PipelinePublicService
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


def _build_project(session: Session, storage, monkeypatch, name: str):
    _patch_queues(monkeypatch)
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
    return project


def test_auto_run_api_full_flow(client, db_session, object_storage, monkeypatch) -> None:
    monkeypatch.setenv("AUTO_RUN_ENABLED", "true")
    monkeypatch.setenv("AUTO_RUN_BUDGET_CNY", "0")
    get_settings.cache_clear()
    project = _build_project(db_session, object_storage, monkeypatch, "自动链接口")

    started = client.post(f"/api/v1/projects/{project.id}/auto-run", json={})
    assert started.status_code == 202, started.text
    data = started.json()["data"]
    assert data["auto_confirmed"] == ["recognition", "main_image", "script", "voice_subtitle"], data
    assert data["stopped_at"] == "content_plan"
    assert data["stopped_reason"] == "human_gate"
    assert data["status"] == "audio_subtitle_confirmed"
    assert data["stage"] == "content_plan", data

    fetched = client.get(f"/api/v1/auto-runs/{data['run_id']}")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["data"]["auto_confirmed_stages"] == data["auto_confirmed"]

    stopped = client.post(f"/api/v1/auto-runs/{data['run_id']}/stop", json={})
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["data"] == {"run_id": data["run_id"], "in_flight": False, "stop_requested": False}

    missing = client.get("/api/v1/auto-runs/run_missing")
    assert missing.status_code == 404

    # 断点续跑：从 stage 处继续（闸口① 未放行 → 仍停在闸口，不重复确认）
    resumed = client.post(f"/api/v1/projects/{project.id}/auto-run", json={"from_stage": "content_plan"})
    assert resumed.status_code == 202, resumed.text
    assert resumed.json()["data"]["auto_confirmed"] == []

    unknown = client.post(f"/api/v1/projects/{project.id}/auto-run", json={"from_stage": "nope"})
    assert unknown.status_code == 422, unknown.text

    # 费用审批入口
    ContentPlanPublicService().generate(db_session, project.id)
    ContentPlanPublicService().confirm(db_session, project.id)
    plan = VideoPlanPublicService().create_plan(
        db_session, project_id=project.id, mode="product", template_id="clean", path="segmented"
    ).plan
    approved = client.post(f"/api/v1/projects/{project.id}/cost-approval", json={"plan_id": plan.id})
    assert approved.status_code == 200, approved.text
    body = approved.json()["data"]
    assert body["plan_id"] == plan.id and body["payload_hash"] and body["approved_by"] == "operator"
    assert body["is_paid"] is False  # mock 下预估为 0：闸门只在真花钱时拦
    assert PipelinePublicService().list_cost_approvals(db_session, project.id)


def test_auto_run_disabled_by_default(client, db_session, object_storage, monkeypatch) -> None:
    monkeypatch.setenv("AUTO_RUN_ENABLED", "false")
    get_settings.cache_clear()
    project = _build_project(db_session, object_storage, monkeypatch, "关闭态")
    response = client.post(f"/api/v1/projects/{project.id}/auto-run", json={})
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "AUTO_RUN_DISABLED"
    run = PipelinePublicService().get_or_create(db_session, project.id)
    assert run.auto_run is False

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
