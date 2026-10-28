"""批次 2b 单测：文案审稿（4 维度 + 只重写不合格的单句）。

VLM/LLM 调用全部打桩（**不联网、不花钱**）；这里验证的是"审稿的约束与降级语义"。
"""
from __future__ import annotations

import json

import httpx
import pytest

from onetake_api.integrations.qwen_vl_script.adapter import (
    REVIEW_DIMENSIONS,
    QwenVlScriptAdapter,
    QwenVlScriptError,
)
from onetake_api.modules.script.domain import ScriptDraft, ScriptInput
from onetake_api.modules.script.service import apply_script_review


def _script_input() -> ScriptInput:
    return ScriptInput(
        product_name="果粒橙", product_note="300ml", pain_point="口渴又不想喝白水",
        selling_points=["30% 鲜橙汁", "不额外加糖"], usage_scenario="办公室下午", offer=None,
    )


def _draft() -> ScriptDraft:
    return ScriptDraft(
        hook="下午三点又渴又困？", pain_point="白水没味道，饮料又怕太甜。",
        selling_points=["30% 鲜橙汁", "不额外加糖"], usage_scenario="放在工位上随时喝。",
        cta="点下方链接带走它。",
    )


def _adapter(handler) -> QwenVlScriptAdapter:
    adapter = QwenVlScriptAdapter(api_key="k", endpoint="https://dashscope.example/vl", model="qwen-vl-plus")
    return adapter


def _patch_post(monkeypatch, handler) -> list[dict]:
    seen: list[dict] = []

    def fake_post(url, *, headers=None, json=None, timeout=None):  # noqa: A002 - 对齐 httpx.post 形参名
        seen.append(json)
        return httpx.Response(200, json=handler(json), request=httpx.Request("POST", url))

    monkeypatch.setattr("onetake_api.integrations.qwen_vl_script.adapter.httpx.post", fake_post)
    return seen


def _review_body(*, revised: dict, passed: dict | None = None) -> dict:
    dimensions = {
        name: {"passed": True if passed is None else passed.get(name, True), "reason": f"{name} ok"}
        for name in REVIEW_DIMENSIONS
    }
    content = json.dumps({"dimensions": dimensions, "revised": revised}, ensure_ascii=False)
    return {"output": {"choices": [{"message": {"content": content}}]}}


def test_review_is_text_only_and_sends_facts_and_dimensions(monkeypatch) -> None:
    seen = _patch_post(monkeypatch, lambda _payload: _review_body(revised={
        "hook": _draft().hook, "pain_point": _draft().pain_point,
        "selling_points": list(_draft().selling_points),
        "usage_scenario": _draft().usage_scenario, "cta": _draft().cta,
    }))
    review = _adapter(None).review(script_input=_script_input(), draft=_draft())

    payload = seen[0]
    content = payload["input"]["messages"][0]["content"]
    assert not any("image" in item for item in content)          # 审稿是纯文本调用（不重复发图）
    text = next(item["text"] for item in content if "text" in item)
    for dimension in REVIEW_DIMENSIONS:
        assert dimension in text
    assert "不得新增事实" in text and "条数必须与输入一致" in text
    assert "果粒橙" in text and "30% 鲜橙汁" in text
    assert review.changed_fields == []                            # 原样返回 → 没有改动
    assert review.failed_dimensions == []


def test_review_reports_only_real_changes(monkeypatch) -> None:
    """模型自称改了但文本没变的，不算改动（`changed_fields` 靠前后比对得出）。"""
    revised = {
        "hook": "下午三点，工位上的你渴了。",                        # 真改了
        "pain_point": _draft().pain_point,                          # 没改
        "selling_points": ["30% 鲜橙汁", "不额外加糖"],              # 没改
        "usage_scenario": _draft().usage_scenario,
        "cta": _draft().cta,
    }
    _patch_post(monkeypatch, lambda _payload: _review_body(revised=revised, passed={"freshness": False}))
    review = _adapter(None).review(script_input=_script_input(), draft=_draft())
    assert review.changed_fields == ["hook"]
    assert review.failed_dimensions == ["freshness"]
    assert review.revised.hook == revised["hook"]


def test_review_rejects_selling_point_count_change(monkeypatch) -> None:
    """卖点条数被改 → 直接报错（审稿不许顺手增删卖点）。"""
    revised = {
        "hook": _draft().hook, "pain_point": _draft().pain_point,
        "selling_points": ["30% 鲜橙汁"],                            # 少了一条
        "usage_scenario": _draft().usage_scenario, "cta": _draft().cta,
    }
    _patch_post(monkeypatch, lambda _payload: _review_body(revised=revised))
    with pytest.raises(QwenVlScriptError):
        _adapter(None).review(script_input=_script_input(), draft=_draft())


def test_review_rejects_missing_dimensions(monkeypatch) -> None:
    body = {"output": {"choices": [{"message": {"content": json.dumps({
        "dimensions": {"rhythm": {"passed": True, "reason": "x"}},
        "revised": {"hook": "a", "pain_point": "b", "selling_points": ["c"],
                    "usage_scenario": "d", "cta": "e"},
    }, ensure_ascii=False)}}]}}
    _patch_post(monkeypatch, lambda _payload: body)
    with pytest.raises(QwenVlScriptError):
        _adapter(None).review(script_input=_script_input(), draft=_draft())


# ---- 接线与降级 ----


class _FakeAdapter:
    def __init__(self, *, review=None, error: Exception | None = None) -> None:
        self.calls = 0
        self._review = review
        self._error = error

    def review(self, *, script_input, draft):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._review


def test_apply_review_uses_revised_draft_when_enabled(monkeypatch) -> None:
    revised = ScriptDraft(
        hook="改过的钩子", pain_point=_draft().pain_point, selling_points=list(_draft().selling_points),
        usage_scenario=_draft().usage_scenario, cta=_draft().cta,
    )
    review = type("R", (), {"revised": revised, "failed_dimensions": ["rhythm"], "changed_fields": ["hook"]})()
    adapter = _FakeAdapter(review=review)
    draft, returned = apply_script_review(adapter, script_input=_script_input(), draft=_draft(), enabled=True)
    assert draft.hook == "改过的钩子" and returned is review and adapter.calls == 1


def test_apply_review_is_skipped_when_disabled() -> None:
    adapter = _FakeAdapter(review=None)
    draft, returned = apply_script_review(adapter, script_input=_script_input(), draft=_draft(), enabled=False)
    assert draft == _draft() and returned is None and adapter.calls == 0     # 默认关闭 → 一次都不调


def test_apply_review_falls_back_to_original_on_failure() -> None:
    adapter = _FakeAdapter(error=QwenVlScriptError("审稿超时"))
    draft, returned = apply_script_review(adapter, script_input=_script_input(), draft=_draft(), enabled=True)
    assert draft == _draft() and returned is None                            # 失败 → 未审稿版本
    assert adapter.calls == 1


def _valid_draft() -> ScriptDraft:
    """合法稿：去掉标点后落在 45~72，且不含任何数字（事实里没有数字）。

    钩子带疑问、场景末尾轻提、cta 是行动号召，否则过不了切片 A 的文案硬规则。
    """
    return ScriptDraft(
        hook="还在为拔干发愁？下午三点又渴又困",
        pain_point="白水没味道，甜饮料又怕腻",
        selling_points=["显色饱满", "不拔干"],
        usage_scenario="通勤和开会前都能用，顺手看看",
        cta="点下方链接带走",
    )


def _script_input2() -> ScriptInput:
    return ScriptInput(
        product_name="口红", product_note=None, pain_point="涂口红容易拔干显唇纹",
        selling_points=["显色饱满", "不拔干"], usage_scenario="通勤补妆", offer=None,
    )


def test_review_rewrite_that_fails_validation_falls_back_to_original() -> None:
    """真机实测踩到：审稿改写稿不满足字数/事实约束 → 原来会让整条文案**生成失败** ✗。

    正确行为：退回**未审稿**版本，并把 review 置空（如实反映"这次没用上审稿"）。
    """
    from onetake_api.modules.script.service import normalize_with_review_fallback

    original = _valid_draft()
    broken = ScriptDraft(                       # 塞了"事实里没有的价格数字" → 过不了数字白名单校验
        hook="这支只要 999 元就能带走，真的很划算值得马上入手",
        pain_point=original.pain_point, selling_points=list(original.selling_points),
        usage_scenario=original.usage_scenario, cta=original.cta,
    )
    review = type("R", (), {"failed_dimensions": ["spoken"], "changed_fields": ["hook"]})()
    normalized, returned = normalize_with_review_fallback(
        reviewed_draft=broken, original_draft=original, script_input=_script_input2(), review=review,
    )
    assert returned is None                                     # 审稿没被用上 → 如实置空
    assert "999" not in normalized.full_text                    # 落的是**未审稿**版本（审稿版里带这个未提供的数字）
    assert original.hook[:6] in normalized.full_text             # 而且确实是原始稿的内容


def test_review_rewrite_that_passes_validation_is_used() -> None:
    from onetake_api.modules.script.service import normalize_with_review_fallback

    review = type("R", (), {"failed_dimensions": [], "changed_fields": ["hook"]})()
    normalized, returned = normalize_with_review_fallback(
        reviewed_draft=_valid_draft(), original_draft=_valid_draft(), script_input=_script_input2(), review=review,
    )
    assert returned is review and normalized.hook == _valid_draft().hook