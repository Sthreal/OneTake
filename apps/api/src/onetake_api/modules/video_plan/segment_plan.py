"""分段 → 供应商调用的**唯一**计划表（S8+S9+S10 补记 5）。

为什么要有它：**分段生成**与**费用预估**必须对同一件事给出同一个答案 ——
「这一镜会调几次供应商、每次多少秒、走哪一档模型（单价不同）」。以前两边各写一套：

* 预估按 i2v 单价把整段秒数算一遍（`i2v_clips` 全记成 i2v）；
* 生成器把超过单次上限的镜**静默钳到上限**（实测 7 秒段 → 只生成 5 秒）。

于是预估与实际双双失真，成片还比配音短 2 秒。现在两边都读这一张表。

**调用计划的三条约定**（都是为了让"末帧锚点"这个既有契约继续成立）：

1. 单次可达（`duration ≤ max_seconds`）→ 一次调用；有尾帧就用**首尾帧对**；
2. 需要切分 → 均分成每份 ≤ 上限的若干次调用；**只有最后一次**能用首尾帧对
   （切分后没有"中段尾帧"，中间子片段只能拿上一片的尾帧续首帧，否则画面会直接跳到段末）；
3. 没有尾帧（例如最后一镜）→ 全部用单帧 i2v。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SegmentCall:
    """一次供应商调用。`pair=True` 表示用首尾帧（kf2v，单价与 i2v 不同）。"""

    order: int
    duration_seconds: int
    pair: bool


def split_durations(total_seconds: int, max_seconds: int) -> list[int]:
    """把总时长均分成每份 ≤ 上限的若干份（先均分、余数依次 +1）。

    **这是全仓唯一的切分算法**：预估（`estimate.py`）与生成（`segment_generation.py`）
    都从这里取，避免"预估按一种切法、生成按另一种切法"。
    """
    total = max(1, int(total_seconds))
    cap = max(1, int(max_seconds))
    count = max(1, -(-total // cap))  # ceil(total / cap)
    base, remainder = divmod(total, count)
    return [base + (1 if index < remainder else 0) for index in range(count)]


def plan_segment_calls(
    *, duration_seconds: int, max_seconds: int, has_tail_frame: bool
) -> list[SegmentCall]:
    """一个分段 → 一串调用（按顺序执行）。见模块 docstring 的三条约定。"""
    durations = split_durations(duration_seconds, max_seconds)
    last_index = len(durations)
    return [
        SegmentCall(
            order=index,
            duration_seconds=seconds,
            pair=bool(has_tail_frame and index == last_index),
        )
        for index, seconds in enumerate(durations, start=1)
    ]
