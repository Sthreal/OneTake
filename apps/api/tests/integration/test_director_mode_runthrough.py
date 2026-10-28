"""导演模式五步（输入 → 分镜 → 素材 → 合成 → 交付）按 UI 调用顺序**连起来**走通一次。

为什么必须有这样一条：每一步的片段测试都可能绿，但"连起来"这一层栽过两次 ——
①「导演模式整页不可达」②「没有视频方案 → 付费入口全 409」。两次的根因都是**顺序 / 前置条件**，
单点测试天然看不见。本用例把 UI（`platform/one-take-backend/web/src/demo/DirectorMode.tsx`）
的真实调用顺序钉住：

    输入  POST /projects → assets/presign → PUT → assets/{id}/complete → POST /auto-run
    分镜  POST /content-plan/confirm（闸①）→ POST /video-plan(path=segmented) → GET estimate
          → 未批准时付费入口 409 → POST /cost-approval（闸②）→ 放行
    素材  GET /video/keyframes → 逐镜 POST .../candidates → POST .../accept
    合成  POST /video/batch?stop_after_segments=1 ×N（逐段推进，不越步）→ 末段走完自动合成
    交付  GET /output → 成片 + 规格（并真把成片读回来一次）

引擎：`MOCK_PROVIDERS=true`（conftest 自动开）+ 本地 FFmpeg ⇒ **零付费调用**。
（只覆盖"结构跑得通 + 闸门在拦"；供应商真实质量不在这里验，见 docs/导演模式与分段可用性总体方案.md。）

**如实登记**：mock 引擎下自动链能不能跑完，取决于 `product_note` 与 mock 文案模板的**长度耦合** ——
mock 文案是固定模板（`integrations/mock_script/adapter.py`），凑不满 45 字下限就报
`SCRIPT_GENERATION_ERROR`；真机靠模型自己写够字数 + 失败重试不受影响。本用例显式带备注绕开它，
没有把这条缺口藏起来。
闸② 的"真花钱"口径用 `Settings(mock_providers=False, …)` **打桩**（只打在 `video_plan.service` 上，
生成链仍旧走 mock）：这样既不花钱，又能验证闸门真的在拦、批准之后真的放行。
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from onetake_api.config import Settings, get_settings
from onetake_api.integrations.object_storage.public import ObjectStoragePublicService

# 自动链跑完前 4 段后可能停在的状态（与前端 `INTAKE_READY_STATUSES` 同一口径）
READY_STATUSES = {
    "audio_subtitle_confirmed",
    "content_plan_ready",
    "content_plan_confirmed",
    "content_qa_passed",
}

# 「会真花钱的配置」：只用来验证闸②，不驱动任何真实适配器
PAID_SETTINGS = Settings(
    mock_providers=False,
    composition_provider="shotstack",
    shotstack_render_price=1.0,
    wan_i2v_provider="mock",
)


class FakeQueue:
    def enqueue(self, *_args, **_kwargs):
        return None


class _StubComposition:
    provider_name = "shotstack"


@pytest.fixture(autouse=True)
def _declare_no_queue_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """宿主机 pytest 与容器**共用同一个 redis**：容器里的 worker 会把自己注册进去。

    本文件用假队列 + 内联推进，所以必须显式声明"队列里没有 worker"，
    否则推进器会等在跑的 worker，测试就永远走不到下一段。
    """
    monkeypatch.setattr("onetake_api.modules.pipeline.orchestrator._queue_has_worker", lambda: False)


@pytest.fixture
def intake_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """把阶段队列换成假队列（**绝不**把 job 塞进真 redis，真 redis 后面坐着真 worker）。"""
    for module in (
        "onetake_api.modules.recognition.service",
        "onetake_api.modules.main_image.service",
        "onetake_api.modules.script.service",
        "onetake_api.modules.voice.service",
        "onetake_api.modules.subtitle.api",
        "onetake_api.modules.video_plan.service",
    ):
        monkeypatch.setattr(f"{module}.get_queue", lambda _name: FakeQueue())
    monkeypatch.setenv("AUTO_RUN_ENABLED", "true")
    get_settings.cache_clear()


def _product_png() -> bytes:
    image = Image.new("RGB", (900, 900), (255, 255, 255))
    product = Image.new("RGB", (300, 460), (28, 120, 210))
    image.paste(product, (300, 220))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _ok(response, *, expect: int | tuple[int, ...] | None = None):
    """断言 HTTP 状态并取 `data` —— 状态码写死在用例里，避免"其实是 4xx 但没人看"。"""
    wanted = (expect,) if isinstance(expect, int) else (expect or ())
    assert response.status_code in wanted or (not wanted and response.status_code < 300), (
        response.status_code,
        response.text[:400],
    )
    return response.json()["data"]


# 备注要一起给：自动链的文案输入是 `product_note` 派生的（痛点 = 卖点 = 备注），
# 而 mock 文案模板再拼一次「还在为…烦恼」——**不给备注就凑不满 45 字的长度下限**，
# script 阶段会 100% 失败（见文末"如实登记"）。真机不受影响（模型自己写够字数）。
PRODUCT_NOTE = "清洗麻烦"


def _intake(client: TestClient, name: str) -> str:
    """输入步：建项目 + 商品图上传（与 `runProjectIntake` 的 file 分支同一串调用）。"""
    project = _ok(
        client.post(
            "/api/v1/projects", json={"product_name": name, "product_note": PRODUCT_NOTE}
        ),
        expect=201,
    )
    project_id = project["project_id"]
    content = _product_png()
    metadata = {
        "original_filename": "product.png",
        "mime_type": "image/png",
        "size_bytes": len(content),
        "width": 900,
        "height": 900,
        "sha256": sha256(content).hexdigest(),
    }
    presigned = _ok(
        client.post(f"/api/v1/projects/{project_id}/assets/presign", json=metadata), expect=201
    )
    upload = httpx.put(
        presigned["upload_url"], content=content, headers={"Content-Type": "image/png"}, timeout=10
    )
    assert upload.status_code == 200
    _ok(
        client.post(
            f"/api/v1/projects/{project_id}/assets/{presigned['asset_id']}/complete", json=metadata
        ),
        expect=(200, 201),
    )
    return project_id


def _run_intake_chain(client: TestClient, project_id: str) -> None:
    """自动链：识别 → 主图 → 文案 → 配音字幕（同步推进；等价于前端 POST /auto-run）。"""
    for _ in range(6):
        _ok(client.post(f"/api/v1/projects/{project_id}/auto-run", json={}), expect=202)
        status = _ok(client.get(f"/api/v1/projects/{project_id}/pipeline"))["status"]
        if status in READY_STATUSES:
            return
    raise AssertionError(f"自动链没有跑到可交付状态，最后停在 {status}（分镜前 4 段是闸① 的前置）")


def test_director_mode_runs_through_all_five_steps(
    client: TestClient,
    db_session: Session,
    object_storage: ObjectStoragePublicService,
    intake_env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ---------- 输入 ----------
    project_id = _intake(client, "导演模式全链路")
    _run_intake_chain(client, project_id)

    # ---------- 分镜 ----------
    content = _ok(client.get(f"/api/v1/projects/{project_id}/content-plan"))
    if content is None:
        content = _ok(client.post(f"/api/v1/projects/{project_id}/content-plan"), expect=201)
    scenes = content["variants"][content["selected_variant_index"]]["scenes"]
    assert len(scenes) >= 2, f"分镜至少要能切段，实际 {len(scenes)}"
    assert all(scene["purpose"] for scene in scenes), "时间线上的每段都要有职能（钩子/卖点/演示/行动号召）"
    assert all(scene["end_seconds"] > scene["start_seconds"] for scene in scenes)

    confirmed = _ok(client.post(f"/api/v1/projects/{project_id}/content-plan/confirm"))
    assert confirmed["status"] == "confirmed", "闸①：分镜必须先确认，后面的付费动作才有依据"

    plan = _ok(
        client.post(
            f"/api/v1/projects/{project_id}/video-plan",
            json={"mode": "product", "template_id": "clean", "path": "segmented"},
        ),
        expect=201,
    )["plan"]
    plan_id = plan["plan_id"]
    assert plan["path"] == "segmented"

    # 闸②：把"当前配置"打桩成会花钱的样子（生成链仍走 mock，不会真调供应商）
    monkeypatch.setattr("onetake_api.modules.video_plan.service.get_settings", lambda: PAID_SETTINGS)
    monkeypatch.setattr(
        "onetake_api.modules.video_plan.service.get_composition_provider", lambda: _StubComposition()
    )
    estimate = _ok(client.get(f"/api/v1/projects/{project_id}/video-plan/{plan_id}/estimate"))
    assert estimate["is_paid"] is True, "打桩成付费配置后预估必须自认付费，否则闸② 形同不存在"
    assert estimate["estimated_known_cost"] > 0, "费用卡要有可显示的数字，不能是 0"
    assert estimate["duration_seconds"] > 0

    blocked = client.post(f"/api/v1/projects/{project_id}/video/batch?stop_after_segments=1")
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"]["code"] == "COST_APPROVAL_REQUIRED", blocked.text

    approval = _ok(
        client.post(
            f"/api/v1/projects/{project_id}/cost-approval",
            json={"plan_id": plan_id, "approved_by": "director-runthrough"},
        )
    )
    assert approval["plan_id"] == plan_id
    assert approval["estimated_cny"] > 0

    # ---------- 素材 ----------
    keyframes = _ok(client.get(f"/api/v1/projects/{project_id}/video/keyframes"))
    assert [slot["scene_id"] for slot in keyframes["keyframes"]] == [scene["scene_id"] for scene in scenes]

    for slot in keyframes["keyframes"]:
        generated = _ok(
            client.post(
                f"/api/v1/projects/{project_id}/video/keyframes/{slot['scene_id']}/candidates",
                json={"mode": "integrated", "n": 1},
            ),
            expect=201,
        )
        refreshed = next(item for item in generated["keyframes"] if item["scene_id"] == slot["scene_id"])
        ready = [item for item in refreshed["candidates"] if item["image_url"] and item["status"] == "ready"]
        assert ready, f"第 {slot['order']} 镜没有可用候选：{refreshed['candidates']}"
        accepted = _ok(
            client.post(
                f"/api/v1/projects/{project_id}/video/keyframes/{slot['scene_id']}/accept",
                json={"keyframe_id": ready[-1]["keyframe_id"]},
            )
        )
        refreshed = next(item for item in accepted["keyframes"] if item["scene_id"] == slot["scene_id"])
        assert refreshed["accepted"] is not None

    # ---------- 合成：逐段推进一段 ----------
    segments = _ok(client.get(f"/api/v1/projects/{project_id}/video/segments"))["segments"]
    total = len(segments)
    assert total == len(scenes), "时间线上的段数必须等于分镜数"
    assert [item["order_index"] for item in segments] == sorted(item["order_index"] for item in segments)

    for step in range(1, total + 1):
        plan_after = _ok(
            client.post(f"/api/v1/projects/{project_id}/video/batch?stop_after_segments=1"), expect=202
        )["plan"]
        current = _ok(client.get(f"/api/v1/projects/{project_id}/video/segments"))["segments"]
        accepted_ids = [item for item in current if item["accepted_candidate_id"]]
        assert len(accepted_ids) == step, f"第 {step} 次点击应只前进一段，实际 {len(accepted_ids)}"
        assert plan_after["batch_status"] == ("done" if step == total else "running"), (
            f"第 {step} 次点击的批状态：{plan_after['batch_status']}"
        )
        if step < total:
            assert plan_after["status"] != "completed", "还没到最后一段就合成 = 越步"

    final_plan = _ok(client.get(f"/api/v1/projects/{project_id}/video"))["plan"]
    assert final_plan["status"] == "completed", final_plan
    assert final_plan["batch_status"] == "done"

    # ---------- 交付 ----------
    output = _ok(client.get(f"/api/v1/projects/{project_id}/output"))
    assert output is not None, "合成完成后交付步必须有成片"
    assert output["download_url"], "交付步必须给可下载地址"
    assert output["size_bytes"] > 1000
    assert output["video_width"] == final_plan["width"] and output["video_height"] == final_plan["height"]
    assert output["duration_seconds"] > 0

    # 交付地址指向 `MINIO_PUBLIC_ENDPOINT`（宿主机视角 `localhost:9000`）—— 容器内连不上那个 host，
    # 而预签名把 host 也算进了签名，换 host 就 403。所以这里按对象键回读一次，验"确实存了真成片"。
    object_key = urlsplit(output["download_url"]).path.split("/", 2)[2]
    assert object_key.startswith(f"projects/{project_id}/"), object_key
    stored = b"".join(object_storage.read_object(object_key=object_key))
    assert len(stored) == output["size_bytes"], "交付地址必须真能取到成片（不是空壳链接）"
    assert stored[4:8] == b"ftyp", "交付的必须是真 MP4"