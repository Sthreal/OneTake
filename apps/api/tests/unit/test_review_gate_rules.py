"""审稿闸纯函数：等长 ±20%、全文 45–72、生成阶段不再自动过闸。不联网。"""
from __future__ import annotations

from onetake_api.config import Settings, get_settings
from onetake_api.integrations.mock_script.adapter import MockScriptAdapter
from onetake_api.integrations.qwen_vl_script.adapter import (
    REVIEW_DIMENSIONS,
    QwenVlScriptError,
    ScriptReview,
)
from onetake_api.modules.script.domain import ScriptDraft, ScriptInput
from onetake_api.modules.script.review_gate import (
    GATE_ENFORCE,
    GATE_OFF,
    assess_revision,
    field_within_tolerance,
    inline_review_enabled,
)


def _chars(count: int) -> str:
    return "字" * count


def _script_input() -> ScriptInput:
    return ScriptInput(
        product_name="口红",
        product_note=None,
        pain_point="涂口红容易拔干显唇纹",
        selling_points=("显色饱满", "不拔干"),
        usage_scenario="通勤补妆",
        offer=None,
    )


def _draft() -> ScriptDraft:
    return ScriptDraft(
        hook="下午三点又渴又困，想喝点提神的",
        pain_point="白水没味道，甜饮料又怕腻",
        selling_points=("显色饱满", "不拔干"),
        usage_scenario="通勤和开会前都能用",
        cta="点下方链接带走",
    )


def test_review_dimensions_stay_the_same() -> None:
    assert REVIEW_DIMENSIONS == ("rhythm", "spoken", "freshness", "structure")


def test_gate_defaults_are_enabled_and_enforce(monkeypatch) -> None:
    monkeypatch.delenv("SCRIPT_REVIEW_ENABLED", raising=False)
    monkeypatch.delenv("SCRIPT_REVIEW_GATE", raising=False)
    get_settings.cache_clear()
    settings = Settings(_env_file=None)
    assert settings.script_review_enabled is True
    assert settings.script_review_gate == GATE_ENFORCE


def test_inline_review_only_when_gate_is_off() -> None:
    assert inline_review_enabled(enabled=True, gate=GATE_OFF) is True
    assert inline_review_enabled(enabled=True, gate="warn") is False
    assert inline_review_enabled(enabled=True, gate=GATE_ENFORCE) is False
    assert inline_review_enabled(enabled=False, gate=GATE_OFF) is False


def test_field_length_tolerance_boundaries() -> None:
    original = _chars(10)
    assert field_within_tolerance(original, _chars(8))
    assert field_within_tolerance(original, _chars(12))
    assert not field_within_tolerance(original, _chars(7))
    assert not field_within_tolerance(original, _chars(13))
    assert field_within_tolerance("你好。", "你好")
    assert not field_within_tolerance("", "多了一个字")


def test_identical_revision_passes_length_and_full_text() -> None:
    assessment = assess_revision(_draft(), _draft(), _script_input())
    assert assessment.ok
    assert assessment.normalized is not None
    assert 45 <= assessment.normalized.character_count <= 72


def test_over_twenty_percent_fails_the_whole_revision() -> None:
    revised = ScriptDraft(
        hook=_draft().hook + "这段改写故意拉得很长已经超过原稿两成",
        pain_point=_draft().pain_point,
        selling_points=_draft().selling_points,
        usage_scenario=_draft().usage_scenario,
        cta=_draft().cta,
    )
    assessment = assess_revision(_draft(), revised, _script_input())
    assert not assessment.ok
    assert assessment.failure_code == "SCRIPT_REVIEW_LENGTH"
    assert "hook" in assessment.length_errors
    assert assessment.normalized is None


def test_unlisted_number_fails_without_counting_as_success() -> None:
    # 字数与原稿钩子对齐，失败原因是未提供的数字，不是等长。
    revised = ScriptDraft(
        hook="下午三点只要999想提神喝",
        pain_point=_draft().pain_point,
        selling_points=_draft().selling_points,
        usage_scenario=_draft().usage_scenario,
        cta=_draft().cta,
    )
    assert field_within_tolerance(_draft().hook, revised.hook)
    assessment = assess_revision(_draft(), revised, _script_input())
    assert not assessment.ok
    assert assessment.failure_code == "SCRIPT_REVIEW_FAILED"
    assert assessment.normalized is None


def test_mock_review_is_configurable_and_defaults_to_passthrough() -> None:
    adapter = MockScriptAdapter()
    before = MockScriptAdapter.review_calls
    review = adapter.review(script_input=_script_input(), draft=_draft())
    assert MockScriptAdapter.review_calls == before + 1
    assert review.revised == _draft()
    assert review.failed_dimensions == []
    assert set(review.dimensions) == set(REVIEW_DIMENSIONS)

    blown = ScriptReview(
        dimensions={name: {"passed": False, "reason": "long"} for name in REVIEW_DIMENSIONS},
        revised=ScriptDraft(
            hook="超长",
            pain_point=_draft().pain_point,
            selling_points=_draft().selling_points,
            usage_scenario=_draft().usage_scenario,
            cta=_draft().cta,
        ),
        changed_fields=["hook"],
        provider="mock",
        model="mock",
    )
    configured = MockScriptAdapter(review_script=blown)
    assert configured.review(script_input=_script_input(), draft=_draft()) is blown

    failing = MockScriptAdapter(review_script=QwenVlScriptError("超时"))
    try:
        failing.review(script_input=_script_input(), draft=_draft())
    except QwenVlScriptError as exc:
        assert exc.message == "超时"
    else:
        raise AssertionError("配置的异常应该原样抛出")
