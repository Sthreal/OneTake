import pytest

from onetake_api.integrations.mock_script.adapter import MockScriptAdapter
from onetake_api.modules.script.content import ScriptGenerationError, normalize_generated, normalize_input
from onetake_api.modules.script.domain import ScriptDraft


def _input():
    return normalize_input(
        product_name="便携榨汁杯",
        product_note="白色杯身",
        pain_point="清洗麻烦",
        selling_points=["杯身可拆卸", "适合随身携带"],
        usage_scenario="通勤和办公室",
        offer=None,
    )


def test_mock_script_matches_length_contract() -> None:
    script_input = _input()
    draft = MockScriptAdapter().generate(image_bytes=b"", mime_type="image/png", script_input=script_input)
    normalized = normalize_generated(draft, script_input)
    assert 85 <= normalized.character_count <= 120
    assert 17 <= normalized.estimated_duration_seconds <= 24
    assert "清洗麻烦" in normalized.full_text
    assert "杯身可拆卸" in normalized.full_text


def test_script_rejects_unprovided_number() -> None:
    draft = ScriptDraft(
        hook="这款商品现在有百分之九十九的用户推荐。",
        pain_point="清洗麻烦，可以重点了解它的实际表现。",
        selling_points=("杯身可拆卸。", "适合随身携带。"),
        usage_scenario="在通勤和办公室时，可以自然使用。",
        cta="想确认这些特点，现在就进一步看看。",
    )
    with pytest.raises(ScriptGenerationError):
        normalize_generated(draft, _input())
