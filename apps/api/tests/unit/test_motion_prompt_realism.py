"""S5 单测：真实感三档、相机冲突 lint、自由文本运镜、各"真实感层"。

**最重要的一条是第一个用例**：它把改动前的输出**原样钉住**——`off` 档必须与 S5 之前逐字一致
（实测对比：`off` × 既有枚举运镜 = 差异 0 处；DB 里出现过的 `camera_move` 只有
`push_in / slow_push_in / tracking`，全是枚举键）。
"""
from __future__ import annotations

import pytest

from onetake_api.integrations.product_scene.style_profiles import get_style_profile
from onetake_api.modules.content_plan.domain import ContentScene
from onetake_api.modules.content_plan.product_shapes import PRODUCT_SHAPES
from onetake_api.modules.video_plan.motion_prompt import (
    BEHAVIOR_BEATS,
    EMOTION_LINES,
    LIVING_BACKGROUNDS,
    OPENER_HANDHELD,
    REALISM_AUTO,
    REALISM_CONSTRAINTS,
    REALISM_OFF,
    build_motion_prompt,
    has_camera_conflict,
    pick_behavior_beats,
    resolve_camera_phrase,
)


def _scene(**kw) -> ContentScene:
    base = dict(
        scene_id="scene_1", order=1, purpose="hook", script_excerpt="文案", start_seconds=0.0,
        end_seconds=3.0, shot_type="lifestyle_scene", prompt="场景目标：pain_point。办公室冷色光线。",
        overlay_product=False, product_position="center", background_style="clean", template_id="clean",
        subtitle_segment_ids=[1], qa_rules=[], visual_goal="pain_point", subject_action="环境轻微变化",
        camera_move="slow_push_in", product_mode="absent", transition="fade",
    )
    base.update(kw)
    return ContentScene(**base)


def _shaped(shape: str, **kw) -> ContentScene:
    """把某个形态的 `visual_hint` 写进场景提示词（规则生成器就是这么写的）。"""
    kw.setdefault("prompt", "展示商品。（商品形态：" + PRODUCT_SHAPES[shape].visual_hint + "）")
    kw.setdefault("overlay_product", True)
    kw.setdefault("product_mode", "overlay")
    kw.setdefault("visual_goal", "product_reveal")
    return _scene(**kw)


# ---------- off 档：历史零行为变更（golden）----------

def test_off_tier_reproduces_the_historical_output_byte_for_byte() -> None:
    expected = (
        "画面从给定首帧的构图与光线开始，不重新构图、不移动主体位置。"
        "运镜：镜头缓慢推近，主体逐渐放大（幅度自然、匀速平稳）。"
        "画面动态：环境轻微变化（光影流动、尘埃浮动），营造真实空间感。"
        "画面稳定，无闪烁、无跳变、无撕裂、无鬼影；不新增文字、水印、多余主体或重复主体。"
    )
    assert build_motion_prompt(_scene(), realism=REALISM_OFF) == expected


def test_default_tier_is_off_so_legacy_callers_are_unaffected() -> None:
    assert build_motion_prompt(_scene()) == build_motion_prompt(_scene(), realism=REALISM_OFF)


def test_off_tier_adds_no_new_layer() -> None:
    prompt = build_motion_prompt(_shaped("apparel"), realism=REALISM_OFF, look=get_style_profile("clean"))
    for marker in ("光线：", "材质约束：", "物理反馈：", "音效：", "惯性", "活体感"):
        assert marker not in prompt


def test_unknown_tier_falls_back_to_off() -> None:
    assert build_motion_prompt(_scene(), realism="不存在的档位") == build_motion_prompt(_scene(), realism=REALISM_OFF)


# ---------- constraints 档 ----------

def test_constraints_adds_look_lock_and_shape_material_constraint() -> None:
    prompt = build_motion_prompt(_shaped("bottle_liquid"), realism=REALISM_CONSTRAINTS, look=get_style_profile("clean"))
    assert "光线：统一为真实商业影棚摄影，冷色干净光线，真实材质，柔和阴影，画面简洁。" in prompt
    assert "材质约束：" in prompt
    # 只加"约束"层，不加"表演"层
    for marker in ("物理反馈：", "音效：", "惯性"):
        assert marker not in prompt


def test_constraints_without_shape_marker_only_adds_look() -> None:
    prompt = build_motion_prompt(_shaped("apparel") , realism=REALISM_CONSTRAINTS, look=get_style_profile("clean"))
    assert "材质约束：" in prompt
    plain = _scene(prompt="没有任何形态标记的场景描述。")
    assert "材质约束：" not in build_motion_prompt(plain, realism=REALISM_CONSTRAINTS, look=get_style_profile("clean"))
    assert "光线：" in build_motion_prompt(plain, realism=REALISM_CONSTRAINTS, look=get_style_profile("clean"))


# ---------- auto 档 ----------

def test_auto_adds_every_new_layer_for_a_person_shot() -> None:
    person = _shaped("apparel", visual_goal="usage_scenario", shot_type="usage_scene", subject_action="模特身着围巾在室内走动")
    prompt = build_motion_prompt(person, realism=REALISM_AUTO, look=get_style_profile("lifestyle"), seed=3)
    for marker in ("光线：", "材质约束：", "物理反馈：", "惯性", "音效：只保留与画面贴合的环境音"):
        assert marker in prompt
    assert any(line[:6] in prompt for line in EMOTION_LINES)
    assert any(line[:6] in prompt for line in LIVING_BACKGROUNDS)


def test_auto_person_layers_are_absent_for_a_product_only_shot() -> None:
    plain_product = _scene(
        overlay_product=True, product_mode="overlay", visual_goal="product_reveal",
        subject_action="灯光扫过瓶身", prompt="展示商品。",
    )
    prompt = build_motion_prompt(plain_product, realism=REALISM_AUTO, look=get_style_profile("clean"))
    assert "惯性" not in prompt          # 布料/头发惯性只给人物镜
    assert "音效：" in prompt             # 音效方向对任何镜都加


def test_auto_is_deterministic_for_the_same_seed() -> None:
    person = _shaped("apparel", subject_action="模特身着围巾", visual_goal="usage_scenario")
    first = build_motion_prompt(person, realism=REALISM_AUTO, seed=11)
    second = build_motion_prompt(person, realism=REALISM_AUTO, seed=11)
    assert first == second


def test_behavior_beats_are_distinct_and_seeded() -> None:
    assert len(set(pick_behavior_beats(0))) == 2
    assert pick_behavior_beats(0) == pick_behavior_beats(0)
    assert pick_behavior_beats(0) != pick_behavior_beats(1)
    assert set(pick_behavior_beats(5)) <= set(BEHAVIOR_BEATS)


# ---------- 相机：lint + 自由文本 ----------

@pytest.mark.parametrize("camera", ["固定镜头环绕主体", "locked off 加 dolly 推近"])
def test_camera_conflict_is_detected(camera: str) -> None:
    assert has_camera_conflict(camera) is True


@pytest.mark.parametrize("camera", ["固定镜头，画面稳定", "缓慢环绕主体", "推近后固定", "先环绕再固定"])
def test_non_conflicting_camera_phrases(camera: str) -> None:
    assert has_camera_conflict(camera) is False


def test_free_text_camera_is_honored_and_conflict_falls_back() -> None:
    assert resolve_camera_phrase(_scene(camera_move="从低角度缓慢环绕瓶身")) == "从低角度缓慢环绕瓶身"
    fallback = resolve_camera_phrase(_scene(camera_move="固定镜头环绕主体"))
    assert fallback.startswith("固定镜头，画面稳定")
    assert "自相矛盾" in fallback


def test_enum_camera_keys_still_go_through_the_existing_table() -> None:
    from onetake_api.modules.content_plan.prompt_schema import camera_move_phrase

    for key in ("push_in", "slow_push_in", "tracking"):
        assert resolve_camera_phrase(_scene(camera_move=key)) == camera_move_phrase(key)


# ---------- opener 前置（默认关）----------

def test_opener_is_off_by_default_and_opt_in() -> None:
    assert not build_motion_prompt(_scene()).startswith(OPENER_HANDHELD)
    assert build_motion_prompt(_scene(), opener=OPENER_HANDHELD).startswith(OPENER_HANDHELD)
