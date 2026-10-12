from __future__ import annotations

from onetake_api.modules.content_plan.domain import ContentScene
from onetake_api.modules.content_plan.prompt_schema import CAMERA_MOVES, build_background_prompt, camera_move_phrase


def _scene(move: str) -> ContentScene:
    return ContentScene(
        scene_id="scene_0", order=0, purpose="展示", script_excerpt="文案", start_seconds=0, end_seconds=5,
        shot_type="medium", prompt="展示", overlay_product=True, product_position="center",
        background_style="clean", template_id="clean", subtitle_segment_ids=[1], qa_rules=[],
        visual_goal="product_reveal", subject_action="展示商品", camera_move=move,
    )


def test_camera_move_phrase_covers_known_moves() -> None:
    assert camera_move_phrase("slow_push_in") == CAMERA_MOVES["slow_push_in"]
    assert "推近" in camera_move_phrase("slow_push_in")
    assert "拉远" in camera_move_phrase("slow_pull_out")
    assert "跟拍" in camera_move_phrase("handheld_follow")


def test_camera_move_phrase_unknown_falls_back_with_marker() -> None:
    phrase = camera_move_phrase("whip_pan_extreme")
    assert CAMERA_MOVES["static"] in phrase
    assert "whip_pan_extreme" in phrase


def test_camera_move_phrase_empty_defaults_to_static() -> None:
    assert camera_move_phrase(None) == CAMERA_MOVES["static"]
    assert camera_move_phrase("") == CAMERA_MOVES["static"]


def test_build_background_prompt_includes_known_camera_phrase() -> None:
    prompt = build_background_prompt(_scene("slow_pan_right"))
    assert camera_move_phrase("slow_pan_right") in prompt
