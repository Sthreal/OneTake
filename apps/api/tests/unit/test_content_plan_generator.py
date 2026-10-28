from onetake_api.modules.content_plan.generator import generate_rule_variants
from onetake_api.modules.content_plan.hook_library import HOOK_IDS, pick_hook
from onetake_api.modules.content_plan.product_shapes import infer_product_shape, shape_hint

STYLE_ORDER = ["clean", "story", "trend", "scene", "pain_point", "product_pov"]


def _segments() -> list[dict]:
    return [
        {"index": 1, "text": "口渴了想喝果汁？", "start": 0.0, "end": 1.6},
        {"index": 2, "text": "试试这款果粒橙。", "start": 1.6, "end": 3.2},
        {"index": 3, "text": "30%鲜橙汁。", "start": 3.2, "end": 7.7},
        {"index": 4, "text": "点击购买。", "start": 7.7, "end": 10.0},
    ]


def test_rule_generator_builds_six_variants_and_keeps_timeline() -> None:
    """批次 2：风格 3 → 6（原 3 档不变、位次不变），时间轴与 product_mode 口径不变。"""
    variants = generate_rule_variants(segments=_segments())
    assert [variant.style for variant in variants] == STYLE_ORDER
    for variant in variants:
        assert len(variant.scenes) == 4
        assert variant.scenes[0].purpose == "hook"
        assert variant.scenes[-1].purpose == "cta"
        assert variant.scenes[0].start_seconds == 0.0
        assert variant.scenes[-1].end_seconds == 14.0
        assert variant.scenes[0].visual_goal == "pain_point"
        assert variant.scenes[0].product_mode == "absent"
        assert variant.scenes[-1].visual_goal == "cta"
        assert all("商品" not in scene.subject_action for scene in variant.scenes)
        assert all(scene.product_mode in {"absent", "overlay", "closeup"} for scene in variant.scenes)
        assert variant.scenes[0].overlay_product is False
        assert all(scene.overlay_product for scene in variant.scenes[1:])


def test_absent_shot_uses_three_part_hook_and_gets_stock_query() -> None:
    """空镜的画面指令来自钩子库（stop；prove；bridge 三段），并带英文检索词；非空镜不给检索词。"""
    variants = generate_rule_variants(segments=_segments())
    hook_scene = variants[0].scenes[0]
    assert hook_scene.subject_action.count("；") == 2          # 三段
    assert "开场" in hook_scene.subject_action
    assert hook_scene.stock_query and hook_scene.stock_query.isascii()
    assert all(
        scene.stock_query == ""
        for variant in variants for scene in variant.scenes if scene.product_mode != "absent"
    )


def test_hook_pick_is_deterministic_per_seed() -> None:
    first = generate_rule_variants(segments=_segments(), seed=0)[0].scenes[0].subject_action
    again = generate_rule_variants(segments=_segments(), seed=0)[0].scenes[0].subject_action
    other = generate_rule_variants(segments=_segments(), seed=1)[0].scenes[0].subject_action
    assert first == again and first != other                  # 同 seed 可复现、不同 seed 会换钩子
    assert pick_hook(style="trend", seed=None).hook_id in HOOK_IDS


def test_hook_prefers_shape_matched_patterns() -> None:
    """形态匹配的钩子（h5 户外光）在给它匹配形态时会被优先选中。"""
    assert pick_hook(style="clean", shape="apparel", seed=None).hook_id == "h5_outdoor_light"
    assert pick_hook(style="clean", shape=None, seed=None).hook_id != "h5_outdoor_light"


def test_product_shape_hint_only_on_product_shots() -> None:
    variants = generate_rule_variants(segments=_segments(), product_name="果粒橙 鲜榨果汁 300ml")
    assert "瓶身与液面" in variants[0].scenes[1].prompt        # 有商品入画 → 加形态倾向（画面倾向文案）
    assert "商品形态" not in variants[0].scenes[0].prompt     # 空镜（无商品）→ 不加


def test_shape_inference_is_deterministic_and_silent_when_unknown() -> None:
    assert infer_product_shape("口红") == "small_item"
    assert infer_product_shape("鲜榨橙汁 300ml") == "bottle_liquid"
    assert infer_product_shape("蓝牙耳机") == "electronics"
    assert infer_product_shape("羊绒围巾") == "apparel"
    assert infer_product_shape("未知玩意儿") is None          # 不认识就不硬猜
    assert infer_product_shape(None, None) is None
    assert shape_hint(None) == ("", "")


def test_llm_templates_avoid_compliance_blocked_styles() -> None:
    """拍板：不引 comparison / unboxing（命中自家 AI_REVIEW_STYLES）。"""
    from onetake_api.modules.content_plan.generator import STYLES

    assert set(STYLES) == set(STYLE_ORDER)
    assert "comparison" not in STYLES and "unboxing" not in STYLES