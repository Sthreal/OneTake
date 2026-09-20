from onetake_api.modules.content_plan.domain import ContentScene
from onetake_api.modules.content_plan.prompt_schema import build_background_negative_prompt, build_background_prompt, from_scene


def _scene(visual_goal: str, product_mode: str) -> ContentScene:
    return ContentScene(
        scene_id="scene_test",
        order=1,
        purpose="selling_point",
        script_excerpt="卖点",
        start_seconds=3.0,
        end_seconds=6.0,
        shot_type="product_reveal",
        prompt="",
        overlay_product=product_mode != "absent",
        product_position="center",
        background_style="clean",
        template_id="clean",
        subtitle_segment_ids=[1],
        qa_rules=["product_visible"],
        visual_goal=visual_goal,
        subject_action="灯光渐亮，背景空间自然变化",
        camera_move="push_in",
        product_mode=product_mode,
        transition="fade",
    )


def test_prompt_schema_builds_background_only_prompt() -> None:
    scene = _scene("product_reveal", "overlay")
    schema = from_scene(scene)
    prompt = build_background_prompt(scene)
    assert schema.version == "v1"
    assert schema.environment
    assert schema.lighting
    assert "商品" not in prompt
    assert "包装" not in prompt
    assert "Logo" not in prompt
    assert "pain_point" not in prompt
    assert "场景目标" not in prompt
    assert "真实商业广告摄影" in prompt


def test_negative_prompt_blocks_product_and_stick_figures() -> None:
    scene = _scene("usage_scenario", "absent")
    negative = build_background_negative_prompt(scene)
    for item in ("商品", "包装", "火柴人", "重复主体", "变形", "动画", "插画"):
        assert item in negative
