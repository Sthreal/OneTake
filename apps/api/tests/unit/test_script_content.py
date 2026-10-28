import pytest

from onetake_api.integrations.mock_script.adapter import MockScriptAdapter
from onetake_api.modules.script.content import (ScriptGenerationError, normalize_generated, normalize_input, spoken_character_count)
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
    assert 45 <= normalized.character_count <= 72
    assert 8 <= normalized.estimated_duration_seconds <= 15
    assert "清洗麻烦" in normalized.full_text
    assert "杯身可拆卸" in normalized.full_text


def test_script_rejects_unprovided_number() -> None:
    draft = ScriptDraft(
        hook="这款商品现在有99%的用户推荐。",
        pain_point="清洗麻烦，可以重点了解它的实际表现。",
        selling_points=("杯身可拆卸。", "适合随身携带。"),
        usage_scenario="在通勤和办公室时，可以自然使用。",
        cta="想确认这些特点，现在就进一步看看。",
    )
    with pytest.raises(ScriptGenerationError):
        normalize_generated(draft, _input())

def test_spoken_count_ignores_our_own_trailing_punctuation() -> None:
    """2026-10-17 实测回归：我们补的句号不能把人顶出 45–72 上限。

    真实事故：模型写的稿 68 字（含它自己的标点），系统给 5 段各补一个句号 → 73 字 → 判不合格，
    整条自动链卡死在"文案"，用户连撞两次。提示词要的是"**去标点** 45–72"，校验也必须同口径。
    """
    script_input = _input()
    draft = ScriptDraft(
        hook="还在盲目护肤？试试精准分层护理",
        pain_point="普通美容仪能量无法深入皮肤各层",
        selling_points=("能量直达不同皮肤深度，实现皮肤的精准分层护理",),
        usage_scenario="日常使用",
        cta="半岛小超炮让你护肤更聪明",
    )
    normalized = normalize_generated(draft, script_input)   # 修复前这里会抛 ScriptGenerationError
    assert 45 <= normalized.character_count <= 72
    assert normalized.full_text.count("。") >= 3            # 句号仍在（给配音/字幕看）
    assert spoken_character_count(normalized.full_text) == normalized.character_count