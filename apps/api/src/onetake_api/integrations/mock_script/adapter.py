from onetake_api.modules.script.content import spoken_character_count
from onetake_api.modules.script.domain import ScriptDraft, ScriptInput

# 场景句收在「顺手看看」，和切片 A 的双 CTA 轻提同一句尾巴，rebase 后仍能过校验。
_LIGHT_TAIL = "顺手看看"
_PAD = "用着也省心"


def _spoken(*parts: str) -> int:
    return spoken_character_count("".join(parts))


def _fit_scenario(hook: str, pain: str, points: list[str], body: str, cta: str) -> str:
    """短输入补到口播字数下限。尾巴始终是轻提，避免把补字贴进 hook。"""
    scenario = f"{body}，{_LIGHT_TAIL}。"
    for _ in range(8):
        if _spoken(hook, pain, "".join(points), scenario, cta) >= 45:
            return scenario
        body = f"{body}{_PAD}"
        scenario = f"{body}，{_LIGHT_TAIL}。"
    return scenario


def _angled_draft(script_input: ScriptInput, angle: str) -> ScriptDraft:
    product = script_input.product_name
    points = [f"{point}。" for point in script_input.selling_points]
    pain = "重点看它的实际表现。"
    if script_input.offer:
        cta = "感兴趣就来看看。"
    else:
        cta = "想确认这些特点，现在就进一步看看。"
    if angle == "scene":
        hook = f"出门时怎么还不用{product}？"
        body = f"在{script_input.usage_scenario}里用"
    elif angle == "comparison":
        hook = f"别再继续为{script_input.pain_point}烦着？"
        body = "比一次就明白"
    else:
        raise ValueError(f"未知文案角度：{angle}")
    return ScriptDraft(
        hook=hook,
        pain_point=pain,
        selling_points=tuple(points),
        usage_scenario=_fit_scenario(hook, pain, points, body, cta),
        cta=cta,
    )


class MockScriptAdapter:
    provider_name = "mock-qwen-vl-plus"
    model = "qwen-vl-plus"

    def generate(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        script_input: ScriptInput,
        angle: str | None = None,
    ) -> ScriptDraft:
        # pain_point / 缺省走原来的痛点模板，旧调用方字数口径不变。
        if angle in {"scene", "comparison"}:
            return _angled_draft(script_input, angle)
        product = script_input.product_name
        hook = f"还在为{script_input.pain_point}烦恼？看看{product}。"
        pain = f"重点看它的实际表现。"
        points = [f"{point}。" for point in script_input.selling_points]
        # 末尾轻提是双 CTA 的前半句（P4A），完整行动号召仍放在 cta，避免把场景句写成第二段广告。
        scenario = "日常用起来很自然，顺手看看。"
        if script_input.offer:
            cta = f"感兴趣就来看看。"
        else:
            cta = "想确认这些特点，现在就进一步看看。"
        return ScriptDraft(
            hook=hook,
            pain_point=pain,
            selling_points=tuple(points),
            usage_scenario=scenario,
            cta=cta,
        )

