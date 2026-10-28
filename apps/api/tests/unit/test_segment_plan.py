"""分段调用计划表（S8+S9+S10 补记 5）。

它存在的理由：**预估与生成必须对同一件事给同一个答案**。改动前两边各写一套，于是
预估按 i2v 单价把整段秒数算一遍、生成器却把超过单次上限的镜**静默钳到上限**（7 秒 → 5 秒）。
"""
from __future__ import annotations

from onetake_api.modules.video_plan.segment_plan import (
    SegmentCall,
    plan_segment_calls,
    split_durations,
)


def test_single_call_when_within_limit() -> None:
    assert plan_segment_calls(duration_seconds=4, max_seconds=5, has_tail_frame=True) == [
        SegmentCall(order=1, duration_seconds=4, pair=True)
    ]
    # 没有尾帧（例如最后一镜）→ 单帧 i2v
    assert plan_segment_calls(duration_seconds=4, max_seconds=5, has_tail_frame=False) == [
        SegmentCall(order=1, duration_seconds=4, pair=False)
    ]


def test_over_limit_splits_and_only_last_call_uses_pair() -> None:
    """7 秒段 + 单次上限 5 秒 → 切成 [4, 3]；**只有最后一次**能用首尾帧对。

    为什么只有最后一次：切分后没有"中段尾帧"，中间子片段只能拿上一片的尾帧续首帧，
    否则画面会直接跳到段末。最后一片才持有真实的下一镜关键帧当尾帧。
    """
    calls = plan_segment_calls(duration_seconds=7, max_seconds=5, has_tail_frame=True)
    assert [(c.order, c.duration_seconds, c.pair) for c in calls] == [
        (1, 4, False),
        (2, 3, True),
    ]


def test_split_without_tail_frame_is_all_single_frame() -> None:
    calls = plan_segment_calls(duration_seconds=12, max_seconds=5, has_tail_frame=False)
    assert [c.duration_seconds for c in calls] == [4, 4, 4]
    assert all(c.pair is False for c in calls)


def test_every_call_within_limit_and_total_preserved() -> None:
    for total in (1, 3, 5, 6, 7, 12, 18, 23):
        for cap in (1, 2, 3, 5, 10):
            durations = split_durations(total, cap)
            assert sum(durations) == total, (total, cap, durations)
            assert all(1 <= d <= cap for d in durations), (total, cap, durations)
            assert len(durations) == len(plan_segment_calls(
                duration_seconds=total, max_seconds=cap, has_tail_frame=True
            ))


def test_degenerate_limits_do_not_crash() -> None:
    # 上限非法（0/负）→ 退化为"每份至少 1 秒"，仍然守恒
    assert split_durations(3, 0) == [1, 1, 1]
    assert split_durations(3, -5) == [1, 1, 1]
    # 总时长非法 → 至少 1 秒
    assert split_durations(0, 5) == [1]
