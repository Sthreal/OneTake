"""口播角度（切片 B）。

一次生成固定三角，不接受请求体改列表（P3A）。第三角按 P2A 叫「对比测评」，
标识是 `comparison`，只写在文案 `facts.angle` 里。

它不是 content_plan 的画面 style。`compliance` 的 `AI_REVIEW_STYLES` 仍然禁止
comparison / 对比测评画面风格；本模块不往分镜风格表里写任何东西。
"""
from __future__ import annotations

DEFAULT_ANGLES: tuple[str, ...] = ("pain_point", "scene", "comparison")

ANGLE_LABELS: dict[str, str] = {
    "pain_point": "痛点种草",
    "scene": "场景安利",
    "comparison": "对比测评",
}

# 与画面 style 同名、但只允许出现在口播角度上的标识。
COPY_ONLY_ANGLES: frozenset[str] = frozenset({"comparison"})

ANGLE_INSTRUCTIONS: dict[str, str] = {
    "pain_point": "痛点种草：开头点出用户正在经历的痛点，再说明商品如何缓解。不要改成其他角度。",
    "scene": "场景安利：开头落在具体使用场景里，让人想到自己会在这个场景用它。不要改成其他角度。",
    "comparison": (
        "对比测评（仅文案）：用口头对比说明和老办法的差别，例如「别再」。"
        "禁止输出画面风格，禁止要求 comparison、对比测评、开箱或 unboxing 画面。"
    ),
}

FACT_ANGLE = "angle"
FACT_ANGLE_INDEX = "angle_index"
FACT_BATCH_ID = "generation_batch_id"
FACT_SELECTED = "selected"


def angle_prompt_suffix(angle: str) -> str:
    try:
        instruction = ANGLE_INSTRUCTIONS[angle]
    except KeyError as exc:
        raise ValueError(f"未知文案角度：{angle}") from exc
    return "口播角度要求（仅文案，不是画面风格）：" + instruction


def is_selected_facts(facts: dict | None) -> bool:
    """没有批次的旧稿视为已选中；同批里只认 `facts.selected`。"""
    payload = facts or {}
    if not payload.get(FACT_BATCH_ID):
        return True
    return bool(payload.get(FACT_SELECTED))
