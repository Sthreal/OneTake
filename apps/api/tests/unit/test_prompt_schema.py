from onetake_api.modules.content_plan.domain import ContentScene
from onetake_api.modules.content_plan.prompt_schema import (
    build_background_negative_prompt,
    build_background_prompt,
    build_keyframe_negative_prompt,
    build_keyframe_prompt,
    build_storyboard_grid_prompt,
    from_scene,
    person_aware_action,
)


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

def _scene_with_no_person() -> ContentScene:
    return ContentScene(
        scene_id="scene_1", order=1, purpose="usage_scenario", script_excerpt="文案",
        start_seconds=0.0, end_seconds=3.0, shot_type="usage_scene", prompt="场景目标：usage_scenario。",
        overlay_product=True, product_position="center", background_style="clean", template_id="clean",
        subtitle_segment_ids=[1], qa_rules=[], visual_goal="usage_scenario",
        subject_action="展示无人物户外运动环境，树叶和光线轻微运动", camera_move="tracking",
        product_mode="overlay", transition="fade",
    )


def test_person_aware_action_rewrites_no_person_phrasing() -> None:
    """绑了出镜人时，"无人物"这类写死的话必须改写 —— 否则提示词自相矛盾（2026-10-16 实测根因）。"""
    assert "无人物" not in person_aware_action("展示无人物户外运动环境")
    assert "出镜人入画" in person_aware_action("展示无人物户外运动环境")
    assert person_aware_action("正常描述") == "正常描述"


def test_keyframe_prompt_with_character_requires_holding_the_product() -> None:
    """关键帧提示词要**明确要求**"这个人手持这个商品"，并按输入图顺序写对编号。"""
    prompt = build_keyframe_prompt(_scene_with_no_person(), None, character_ref=2, product_ref=1)
    assert "图 2" in prompt and "图 1" in prompt
    assert "手持" in prompt
    assert "必须是同一个人" in prompt
    # 没有出镜人时不得凭空出现人物指令（老行为逐字不变）
    plain = build_keyframe_prompt(_scene_with_no_person(), None)
    assert "图 2" not in plain and "手持" not in plain


def test_storyboard_grid_prompt_with_character_keeps_one_person_per_cell() -> None:
    prompt = build_storyboard_grid_prompt(2, 2, character_ref=2)
    assert "图 2" in prompt and "手持" in prompt
    assert "同一个人" in prompt


def test_keyframe_negative_prompt_adds_person_pollution_terms_only_when_needed() -> None:
    scene = _scene_with_no_person()
    base = build_keyframe_negative_prompt(scene, None)
    with_person = build_keyframe_negative_prompt(scene, None, with_character=True)
    assert "第二个人" not in base
    assert "第二个人" in with_person and "换脸" in with_person