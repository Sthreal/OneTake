from onetake_api.modules.content_plan.generator import generate_rule_variants


def test_rule_generator_builds_three_variants_and_keeps_timeline() -> None:
    segments = [
        {"index": 1, "text": "口渴了想喝果汁？", "start": 0.0, "end": 1.6},
        {"index": 2, "text": "试试这款果粒橙。", "start": 1.6, "end": 3.2},
        {"index": 3, "text": "30%鲜橙汁。", "start": 3.2, "end": 7.7},
        {"index": 4, "text": "点击购买。", "start": 7.7, "end": 10.0},
    ]
    variants = generate_rule_variants(segments=segments)
    assert [variant.style for variant in variants] == ["clean", "story", "trend"]
    for variant in variants:
        assert len(variant.scenes) == 4
        assert variant.scenes[0].purpose == "hook"
        assert variant.scenes[-1].purpose == "cta"
        assert variant.scenes[0].start_seconds == 0.0
        assert variant.scenes[-1].end_seconds == 10.0
        assert all(scene.overlay_product for scene in variant.scenes)
