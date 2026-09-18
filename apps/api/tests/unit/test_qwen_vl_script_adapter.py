from io import BytesIO

import pytest
from PIL import Image

from onetake_api.integrations.qwen_vl_script.adapter import QwenVlScriptAdapter, QwenVlScriptError
from onetake_api.modules.script.domain import ScriptInput


def _png() -> bytes:
    output = BytesIO()
    Image.new("RGBA", (240, 240), (30, 120, 220, 255)).save(output, format="PNG")
    return output.getvalue()


def _input() -> ScriptInput:
    return ScriptInput(
        product_name="便携榨汁杯",
        product_note="白色杯身",
        pain_point="清洗麻烦",
        selling_points=("杯身可拆卸", "适合随身携带"),
        usage_scenario="通勤和办公室",
        offer=None,
    )


class FakeResponse:
    def __init__(self, text: str) -> None:
        self._text = text

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"output": {"choices": [{"message": {"content": [{"text": self._text}]}}]}}


def _valid_json(points: str) -> str:
    return (
        '{"hook":"还在为清洗麻烦烦恼吗？",'
        '"pain_point":"针对清洗麻烦，可以重点了解它的实际表现。",'
        '"selling_points":' + points + ','
        '"usage_scenario":"在通勤和办公室时，可以自然使用。",'
        '"cta":"想确认这些特点，现在就进一步看看。"}'
    )


def test_qwen_vl_script_parses_structured_json(monkeypatch) -> None:
    captured = {}

    def fake_post(url, *, headers, json, timeout):
        captured["json"] = json
        captured["headers"] = headers
        return FakeResponse(_valid_json('["杯身可拆卸。","适合随身携带。"]'))

    monkeypatch.setattr("onetake_api.integrations.qwen_vl_script.adapter.httpx.post", fake_post)
    adapter = QwenVlScriptAdapter(api_key="test-key", endpoint="https://example.test/script", model="qwen-vl-plus")
    draft = adapter.generate(image_bytes=_png(), mime_type="image/png", script_input=_input())
    assert draft.pain_point == "针对清洗麻烦，可以重点了解它的实际表现。"
    assert draft.selling_points == ("杯身可拆卸", "适合随身携带")
    assert captured["json"]["model"] == "qwen-vl-plus"


def test_qwen_vl_script_rejects_invalid_json(monkeypatch) -> None:
    monkeypatch.setattr(
        "onetake_api.integrations.qwen_vl_script.adapter.httpx.post",
        lambda *args, **kwargs: FakeResponse("这不是 JSON"),
    )
    adapter = QwenVlScriptAdapter(api_key="test-key", endpoint="https://example.test/script", model="qwen-vl-plus")
    with pytest.raises(QwenVlScriptError):
        adapter.generate(image_bytes=_png(), mime_type="image/png", script_input=_input())


def test_qwen_vl_script_uses_authoritative_input_selling_points(monkeypatch) -> None:
    monkeypatch.setattr(
        "onetake_api.integrations.qwen_vl_script.adapter.httpx.post",
        lambda *args, **kwargs: FakeResponse(_valid_json('["杯身可拆卸。","适合随身携带。","额外增加的卖点。"]')),
    )
    adapter = QwenVlScriptAdapter(api_key="test-key", endpoint="https://example.test/script", model="qwen-vl-plus")
    draft = adapter.generate(image_bytes=_png(), mime_type="image/png", script_input=_input())
    assert draft.selling_points == ("杯身可拆卸", "适合随身携带")
