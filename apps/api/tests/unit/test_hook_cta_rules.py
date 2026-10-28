"""切片 A：文案钩子 / 双 CTA 硬规则，以及画面钩子库、3 秒入画、中段续命。"""
from io import BytesIO

import pytest
from PIL import Image

from onetake_api.integrations.qwen_vl_script.adapter import QwenVlScriptAdapter
from onetake_api.modules.content_plan.generator import (
    PRODUCT_IN_FRAME_DEADLINE_SECONDS,
    USAGE_RETENTION_CUE,
    generate_rule_variants,
    second_shot_product_in_frame,
)
from onetake_api.modules.content_plan.hook_library import HOOK_IDS, HOOK_PATTERNS, pick_hook
from onetake_api.modules.script.content import (
    MAX_CHARACTERS,
    MIN_CHARACTERS,
    ScriptGenerationError,
    normalize_generated,
    normalize_input,
    spoken_character_count,
)
from onetake_api.modules.script.copy_rules import COPY_RULE_PROMPT, find_copy_violations
from onetake_api.modules.script.domain import ScriptDraft, ScriptInput

LEGACY_HOOK_IDS = {
    "h1_desk_fatigue",
    "h2_sudden_detail",
    "h3_scene_promise",
    "h4_before_after_space",
    "h5_outdoor_light",
    "h6_clean_studio",
}
TRUST_HOOK_IDS = {
    "h7_trusted_hands",
    "h8_used_trace",
    "h9_shared_table",
    "h10_second_reach",
    "h11_blank_note",
}


def _input() -> ScriptInput:
    return normalize_input(
        product_name="便携榨汁杯",
        product_note="白色杯身",
        pain_point="清洗麻烦",
        selling_points=["杯身可拆卸", "适合随身携带"],
        usage_scenario="通勤和办公室",
        offer=None,
    )


def _draft(**overrides) -> ScriptDraft:
    payload = dict(
        hook="还在为清洗发愁？先看这一下",
        pain_point="杯身难拆洗起来费时间",
        selling_points=("杯身可拆卸", "适合随身携带"),
        usage_scenario="通勤路上用完顺手看看",
        cta="想确认就现在看看",
    )
    payload.update(overrides)
    return ScriptDraft(**payload)


def _normalize(**overrides):
    return normalize_generated(_draft(**overrides), _input())


def test_opening_cliche_fails_and_names_freshness() -> None:
    with pytest.raises(ScriptGenerationError) as exc:
        _normalize(hook="大家好，今天给大家介绍这杯")
    assert exc.value.code == "SCRIPT_GENERATION_ERROR"
    assert exc.value.rule == "opening_cliche"
    assert exc.value.dimension == "freshness"
    assert "大家好" in exc.value.message
    assert "opening_cliche" in exc.value.message

    with pytest.raises(ScriptGenerationError) as intro:
        _normalize(hook="今天给大家介绍这只杯子呀")
    assert intro.value.rule == "opening_cliche"
    assert "今天给大家介绍" in intro.value.message


def test_cliche_only_counts_at_the_opening() -> None:
    normalized = _normalize(hook="还在纠结？大家好其实不是重点")
    assert MIN_CHARACTERS <= normalized.character_count <= MAX_CHARACTERS
    assert find_copy_violations(
        hook=normalized.hook,
        usage_scenario=normalized.usage_scenario,
        cta=normalized.cta,
    ) == []


def test_short_hook_fails_thumbstop_even_with_a_question() -> None:
    with pytest.raises(ScriptGenerationError) as exc:
        _normalize(hook="看这个？")
    assert exc.value.rule == "hook_thumbstop"
    assert "structure" in exc.value.message
    assert "至少需要" in exc.value.message


def test_hook_without_conflict_fails_thumbstop() -> None:
    with pytest.raises(ScriptGenerationError) as exc:
        _normalize(hook="这款杯子日常很好用")
    assert exc.value.rule == "hook_thumbstop"
    assert "疑问或冲突" in exc.value.message


def test_dual_cta_requires_light_mention_and_closing_action() -> None:
    with pytest.raises(ScriptGenerationError) as usage_exc:
        _normalize(usage_scenario="通勤和办公室")
    assert usage_exc.value.rule == "dual_cta_usage"
    assert "45–72" in usage_exc.value.message

    with pytest.raises(ScriptGenerationError) as cta_exc:
        _normalize(cta="这款杯子很适合你")
    assert cta_exc.value.rule == "dual_cta_closing"
    assert "行动号召" in cta_exc.value.message


def test_valid_script_stays_inside_character_budget() -> None:
    normalized = _normalize()
    assert MIN_CHARACTERS <= normalized.character_count <= MAX_CHARACTERS
    assert normalized.full_text.endswith("看看。")
    assert spoken_character_count(normalized.usage_scenario) >= 4
    assert "顺手看看" in normalized.usage_scenario


def test_generate_and_review_prompts_share_the_copy_contract(monkeypatch) -> None:
    seen: list[dict] = []

    def fake_post(url, *, headers=None, json=None, timeout=None):  # noqa: A002
        seen.append(json)
        return type("R", (), {
            "raise_for_status": lambda self: None,
            "json": lambda self: {"output": {"choices": [{"message": {"content": "not-json"}}]}},
        })()

    monkeypatch.setattr("onetake_api.integrations.qwen_vl_script.adapter.httpx.post", fake_post)
    adapter = QwenVlScriptAdapter(api_key="k", endpoint="https://example.test/script", model="qwen-vl-plus")
    image = BytesIO()
    Image.new("RGB", (32, 32), (20, 20, 20)).save(image, format="PNG")
    with pytest.raises(Exception):
        adapter.generate(image_bytes=image.getvalue(), mime_type="image/png", script_input=_input())
    generate_text = seen[0]["input"]["messages"][0]["content"][1]["text"]
    assert COPY_RULE_PROMPT in generate_text
    assert "大家好" in generate_text and "顺手看看" in generate_text

    with pytest.raises(Exception):
        adapter.review(script_input=_input(), draft=_draft())
    review_text = seen[1]["input"]["messages"][0]["content"][0]["text"]
    assert COPY_RULE_PROMPT in review_text
    assert "freshness.passed 必须为 false" in review_text
    assert "structure.passed 必须为 false" in review_text


def test_hook_library_grows_trust_patterns_without_rewriting_speech() -> None:
    assert len(HOOK_PATTERNS) >= 10
    assert len(HOOK_IDS) == len(set(HOOK_IDS)) == len(HOOK_PATTERNS)
    assert LEGACY_HOOK_IDS <= set(HOOK_IDS)
    assert TRUST_HOOK_IDS <= set(HOOK_IDS)
    for pattern in HOOK_PATTERNS:
        assert "商品" not in pattern.instruction
        assert pattern.stop.startswith("开场")
        assert pattern.stock_query.isascii() and pattern.stock_query
    # 信任型条目仍是画面指令：不写口播套话，也不给可读评价。
    note = next(item for item in HOOK_PATTERNS if item.hook_id == "h11_blank_note")
    assert "可读" in note.prove
    assert "大家好" not in note.instruction


def test_trust_hooks_are_selectable() -> None:
    seen = {pick_hook(style="clean", seed=seed).hook_id for seed in range(12)}
    seen |= {pick_hook(style="trend", seed=seed).hook_id for seed in range(12)}
    assert seen & TRUST_HOOK_IDS


def test_second_shot_shows_product_by_three_seconds_and_usage_holds_attention() -> None:
    variants = generate_rule_variants(
        segments=[{"index": 1, "text": "口渴了想喝果汁？", "start": 0.0, "end": 14.0}],
    )
    assert variants
    for variant in variants:
        assert second_shot_product_in_frame(variant.scenes)
        second = variant.scenes[1]
        assert second.end_seconds <= PRODUCT_IN_FRAME_DEADLINE_SECONDS <= 3.0
        assert second.product_mode != "absent"
        assert variant.scenes[0].product_mode == "absent"
        assert variant.scenes[0].end_seconds <= second.end_seconds
        usage = variant.scenes[2]
        assert usage.purpose == "usage_scenario"
        assert USAGE_RETENTION_CUE in usage.subject_action
        assert USAGE_RETENTION_CUE in usage.prompt
        assert variant.scenes[-1].end_seconds <= 15
        assert "商品" not in usage.subject_action
