"""商品场景相关测试（M4-03 之后只剩「入画路线」的部分）。

**为什么文件名没改**：本文件原先主要测 `ProductSceneAdapter`（生成空背景 + 动背景 —— 即已被
废弃的「背景 + 叠商品」路线）。那条路线连同 `background_keyframe.py` 与 `adapter.py` 已整体删除，
本文件现在只保留**入画路线**用到的场景素材断言，以及若干"废弃路径不得复活"的守卫。
按 `AGENTS.md` §三 不做未授权的重命名/删除，故文件名保持不变。
"""
from __future__ import annotations

import importlib
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

from onetake_api.modules.video_plan.service import VideoPlanApplicationService


def test_scene_assets_are_vertical() -> None:
    """入画关键帧用到的场景底图仍按成片分辨率渲染，且提示词里不出现商品。"""
    from onetake_api.integrations.product_scene.scene_assets import load_scene_keyframe, scene_prompt

    for goal in ("pain_point", "product_reveal", "usage_scenario", "cta"):
        with Image.open(BytesIO(load_scene_keyframe(goal))) as image:
            # 场景素材按成片目标分辨率渲染（与 plan.width/height 一致）
            assert image.size == (1080, 1920)
        prompt = scene_prompt(goal)
        assert "商品" not in prompt
        assert "包装" not in prompt


def test_create_base_video_no_longer_routes_to_the_product_scene_pipeline(monkeypatch) -> None:
    """M4-03 提交 1：「生成背景 + 叠商品」整片路径已废弃。

    三种商品模板现在一律走 `render_base_video`（那是**基片**；真实分段生成在 segment_service），
    不再路由到已删除的 product_scene 管线。
    """
    import onetake_api.modules.video_plan.service as service_module

    monkeypatch.setattr(service_module, "get_settings", lambda: SimpleNamespace(mock_providers=True))
    seen: list[str | None] = []
    monkeypatch.setattr(
        service_module,
        "render_base_video",
        lambda *, image_bytes, mode, template_id, **_kwargs: seen.append(template_id) or b"base",
    )
    service = VideoPlanApplicationService(composition=SimpleNamespace(provider_name="mock-video"))

    for template_id in ("clean", "dynamic", "lifestyle"):
        plan = SimpleNamespace(
            mode="product", template_id=template_id, duration_seconds=18,
            width=1080, height=1920, fps=30, path="segmented",
        )
        assert service._create_base_video(None, plan, b"main-image", None) == b"base"

    assert seen == ["clean", "dynamic", "lifestyle"]


def test_product_scene_pipeline_helpers_must_not_come_back() -> None:
    """M4-03 提交 1 的回归守卫：被废弃路径的三个入口**不得复活**。

    这条断言比"删掉旧测试"更有价值 —— 它防的是"以后有人再把那条路径加回来"。
    """
    for name in ("_uses_product_scene", "_create_product_scene_video", "_product_scene_config_errors"):
        assert not hasattr(VideoPlanApplicationService, name), f"{name} 又回来了？"


@pytest.mark.parametrize(
    "module",
    (
        "onetake_api.integrations.product_scene.background_keyframe",
        "onetake_api.integrations.product_scene.adapter",
    ),
)
def test_background_generation_modules_must_not_come_back(module: str) -> None:
    """M4-03 提交 3：整条「生成背景」路线的模块也不得复活。"""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module)