from __future__ import annotations

import re
from dataclasses import dataclass

from onetake_api.modules.script.domain import ScriptDraft, ScriptInput
from onetake_api.platform.errors import DomainError

MIN_CHARACTERS = 65
MAX_CHARACTERS = 120
MAX_SELLING_POINTS = 5
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?%?")
_SPACE_RE = re.compile(r"\s+")


class ScriptValidationError(DomainError):
    code = "SCRIPT_VALIDATION_ERROR"
    http_status = 422


class ScriptGenerationError(DomainError):
    code = "SCRIPT_GENERATION_ERROR"
    http_status = 502
    retryable = True


@dataclass(frozen=True)
class NormalizedScript:
    hook: str
    pain_point: str
    selling_points: list[str]
    usage_scenario: str
    offer: str | None
    cta: str
    full_text: str
    character_count: int
    estimated_duration_seconds: float


def _clean(value: str) -> str:
    return _SPACE_RE.sub(" ", value).strip()


def _sentence(value: str) -> str:
    text = _clean(value).strip("。！？!?；;，,")
    return f"{text}。" if text else ""


def normalize_input(
    *,
    product_name: str,
    product_note: str | None,
    pain_point: str,
    selling_points: list[str],
    usage_scenario: str,
    offer: str | None,
) -> ScriptInput:
    name = _clean(product_name)
    pain = _clean(pain_point)
    scenario = _clean(usage_scenario)
    points = [_clean(point) for point in selling_points if _clean(point)]
    normalized_offer = _clean(offer) if offer else None

    if not name:
        raise ScriptValidationError("商品名称不能为空")
    if not 2 <= len(pain) <= 80:
        raise ScriptValidationError("痛点需为 2–80 个字符")
    if not 1 <= len(points) <= MAX_SELLING_POINTS:
        raise ScriptValidationError("卖点需为 1–5 条")
    if any(len(point) > 60 for point in points):
        raise ScriptValidationError("单条卖点不能超过 60 个字符")
    if not 2 <= len(scenario) <= 100:
        raise ScriptValidationError("使用场景需为 2–100 个字符")
    if normalized_offer and len(normalized_offer) > 80:
        raise ScriptValidationError("优惠信息不能超过 80 个字符")

    return ScriptInput(
        product_name=name,
        product_note=_clean(product_note) if product_note else None,
        pain_point=pain,
        selling_points=tuple(points),
        usage_scenario=scenario,
        offer=normalized_offer,
    )


def _numeric_facts(script_input: ScriptInput) -> set[str]:
    values = [
        script_input.product_name,
        script_input.product_note or "",
        script_input.pain_point,
        *script_input.selling_points,
        script_input.usage_scenario,
        script_input.offer or "",
    ]
    return set(_NUMBER_RE.findall(" ".join(values)))


def normalize_generated(
    draft: ScriptDraft,
    script_input: ScriptInput,
) -> NormalizedScript:
    hook = _clean(draft.hook)
    pain = _clean(draft.pain_point)
    points = [_clean(point) for point in draft.selling_points if _clean(point)]
    scenario = _clean(draft.usage_scenario)
    cta = _clean(draft.cta)
    if not hook or not pain or not scenario or not cta:
        raise ScriptGenerationError("文案结构不完整")
    if not 1 <= len(points) <= MAX_SELLING_POINTS:
        raise ScriptGenerationError("模型返回的卖点数量无效")

    full_text = "".join(
        _sentence(value)
        for value in [hook, pain, *points, scenario, cta]
    )
    if "http://" in full_text or "https://" in full_text:
        raise ScriptGenerationError("文案不能包含外部链接")
    generated_numbers = set(_NUMBER_RE.findall(full_text))
    if not generated_numbers.issubset(_numeric_facts(script_input)):
        raise ScriptGenerationError("文案包含未提供的事实数字")

    character_count = len(_SPACE_RE.sub("", full_text))
    if not MIN_CHARACTERS <= character_count <= MAX_CHARACTERS:
        raise ScriptGenerationError(f"文案长度需为 {MIN_CHARACTERS}–{MAX_CHARACTERS} 个字符")

    return NormalizedScript(
        hook=hook,
        pain_point=pain,
        selling_points=points,
        usage_scenario=scenario,
        offer=script_input.offer,
        cta=cta,
        full_text=full_text,
        character_count=character_count,
        estimated_duration_seconds=round(character_count / 3.5, 1),
    )


def normalize_edited(
    *,
    current: NormalizedScript,
    hook: str | None = None,
    pain_point: str | None = None,
    selling_points: list[str] | None = None,
    usage_scenario: str | None = None,
    cta: str | None = None,
    script_input: ScriptInput,
) -> NormalizedScript:
    return normalize_generated(
        ScriptDraft(
            hook=hook if hook is not None else current.hook,
            pain_point=pain_point if pain_point is not None else current.pain_point,
            selling_points=tuple(selling_points if selling_points is not None else current.selling_points),
            usage_scenario=usage_scenario if usage_scenario is not None else current.usage_scenario,
            cta=cta if cta is not None else current.cta,
        ),
        script_input,
    )
