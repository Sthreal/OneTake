"""关键帧「静态告警」纯规则（S5 #11）。

**为什么**：关键帧生成是**静帧**——提示词里若含时序词（"先…再…""逐渐""随后"），
模型只能挑一个瞬间画，结果往往既不像开头也不像结尾（ClipForge 的 `keyframeStaticWarn` 同一意图）。

本模块只做**判定与措辞**，不调用、不落库：调用方（生成侧日志 / 前端 / 未来的校验器）自行决定怎么提示。
判定是子串匹配一个**封闭词表**（可测、可解释），命中即原样返回命中词，不做近义推断。
"""
from __future__ import annotations

# 时序/过程类词（出现在关键帧提示词里意味着"这一刻画不出来"）
TEMPORAL_WORDS: tuple[str, ...] = (
    "先", "然后", "随后", "接着", "最后", "逐渐", "越来越", "渐渐", "缓慢地变",
    "之后", "同时", "一边", "一边", "直到", "突然", "瞬间变化",
)


def find_temporal_words(prompt: str | None) -> list[str]:
    """返回提示词里命中的时序词（去重、保持词表顺序）；没有则返回空列表。"""
    text = prompt or ""
    return [word for word in dict.fromkeys(TEMPORAL_WORDS) if word and word in text]


def static_warning(prompt: str | None) -> str | None:
    """命中时序词时给出**一句人话**告警；没命中返回 None（不打扰）。"""
    words = find_temporal_words(prompt)
    if not words:
        return None
    return (
        f"关键帧提示词含时序词（{'、'.join(words)}）：静帧只能画一个瞬间，"
        "建议改成\"动作开始前一瞬\"的定格写法再生成"
    )
