"""切片 B：三个口播角度的模板、prompt，以及 comparison 不进画面 style。"""
from io import BytesIO

import pytest
from PIL import Image

from onetake_api.integrations.mock_script.adapter import MockScriptAdapter
from onetake_api.integrations.qwen_vl_script.adapter import QwenVlScriptAdapter, QwenVlScriptError
from onetake_api.modules.compliance.platform_rules import AI_REVIEW_STYLES
from onetake_api.modules.content_plan.generator import STYLES
from onetake_api.modules.script.angles import (
    ANGLE_LABELS,
    COPY_ONLY_ANGLES,
    DEFAULT_ANGLES,
    angle_prompt_suffix,
)
from onetake_api.modules.script.content import normalize_generated, normalize_input
from onetake_api.modules.script.domain import ScriptInput


def _input(**overrides) -> ScriptInput:
    payload = dict(
        product_name="便携榨汁杯",
        product_note="白色杯身",
        pain_point="清洗麻烦",
        selling_points=["杯身可拆卸", "适合随身携带"],
        usage_scenario="通勤和办公室",
        offer=None,
    )
    payload.update(overrides)
    return normalize_input(**payload)


def _png() -> bytes:
    output = BytesIO()
    Image.new("RGBA", (240, 240), (30, 120, 220, 255)).save(output, format="PNG")
    return output.getvalue()


def test_default_angles_are_fixed_triangle_and_comparison_is_copy_only() -> None:
    assert DEFAULT_ANGLES == ("pain_point", "scene", "comparison")
    assert ANGLE_LABELS["comparison"] == "对比测评"
    assert "comparison" in COPY_ONLY_ANGLES
    assert COPY_ONLY_ANGLES.isdisjoint(STYLES)
    assert "comparison" in AI_REVIEW_STYLES
    assert "对比测评" in AI_REVIEW_STYLES
    assert ANGLE_LABELS["comparison"] not in STYLES


def test_unknown_angle_is_rejected_before_prompt_use() -> None:
    with pytest.raises(ValueError):
        angle_prompt_suffix("diff_or_trust")


def test_mock_angles_differ_and_fit_length() -> None:
    script_input = _input()
    adapter = MockScriptAdapter()
    drafts = {
        angle: adapter.generate(image_bytes=b"", mime_type="image/png", script_input=script_input, angle=angle)
        for angle in DEFAULT_ANGLES
    }
    default = adapter.generate(image_bytes=b"", mime_type="image/png", script_input=script_input)
    assert drafts["pain_point"] == default
    hooks = {draft.hook for draft in drafts.values()}
    scenarios = {draft.usage_scenario for draft in drafts.values()}
    assert len(hooks) == 3
    assert len(scenarios) == 3
    assert "清洗麻烦" in drafts["pain_point"].hook
    assert "通勤和办公室" in drafts["scene"].usage_scenario
    assert "怎么还" in drafts["scene"].hook
    assert drafts["comparison"].hook.startswith("别再")
    assert "比一次就明白" in drafts["comparison"].usage_scenario
    for draft in drafts.values():
        normalized = normalize_generated(draft, script_input)
        assert 45 <= normalized.character_count <= 72


def test_mock_short_input_still_reaches_minimum() -> None:
    script_input = ScriptInput(
        product_name="杯",
        product_note=None,
        pain_point="脏",
        selling_points=("轻",),
        usage_scenario="家",
        offer=None,
    )
    adapter = MockScriptAdapter()
    for angle in ("scene", "comparison"):
        draft = adapter.generate(image_bytes=b"", mime_type="image/png", script_input=script_input, angle=angle)
        normalized = normalize_generated(draft, script_input)
        assert 45 <= normalized.character_count <= 72
        assert normalized.usage_scenario.endswith("顺手看看。")


def test_qwen_angle_prompt_is_appended_without_live_call(monkeypatch) -> None:
    captured: list[str] = []

    def fake_post(url, *, headers, json, timeout):
        captured.append(json["input"]["messages"][0]["content"][1]["text"])

        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                text = (
                    '{"hook":"还在为清洗麻烦烦恼吗？","pain_point":"重点看实际表现。",'
                    '"selling_points":["杯身可拆卸。","适合随身携带。"],'
                    '"usage_scenario":"通勤时用。","cta":"现在就来看看。"}'
                )
                return {"output": {"choices": [{"message": {"content": [{"text": text}]}}]}}

        return FakeResponse()

    monkeypatch.setattr("onetake_api.integrations.qwen_vl_script.adapter.httpx.post", fake_post)
    adapter = QwenVlScriptAdapter(api_key="test-key", endpoint="https://example.test/script", model="qwen-vl-plus")
    script_input = _input()
    adapter.generate(image_bytes=_png(), mime_type="image/png", script_input=script_input)
    adapter.generate(image_bytes=_png(), mime_type="image/png", script_input=script_input, angle="comparison")
    assert "口播角度要求" not in captured[0]
    assert "口播角度要求" in captured[1]
    assert "对比测评" in captured[1]
    assert "禁止输出画面风格" in captured[1]
    assert "unboxing" in captured[1]


def test_qwen_unknown_angle_does_not_call_provider(monkeypatch) -> None:
    def fake_post(*_args, **_kwargs):
        raise AssertionError("未知角度不应该打到 provider")

    monkeypatch.setattr("onetake_api.integrations.qwen_vl_script.adapter.httpx.post", fake_post)
    adapter = QwenVlScriptAdapter(api_key="test-key", endpoint="https://example.test/script", model="qwen-vl-plus")
    with pytest.raises(QwenVlScriptError):
        adapter.generate(image_bytes=_png(), mime_type="image/png", script_input=_input(), angle="diff_or_trust")
