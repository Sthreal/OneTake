"""S1 跨段曝光对齐的单测。

分三层：
1. **纯逻辑**（阈值判定 / 中位数目标 / 上限钳制）—— 不需要 ffmpeg；
2. **注入假实现**（零重编码契约、每段都过一遍重编码）—— 不需要 ffmpeg；
3. **真 ffmpeg 冒烟**（测量回路 + 对齐后真实收敛）—— 数字来自 2026-10-15 的标定：
   `eq=brightness` 每单位约推动 240~290 灰阶，故 `delta = (目标-实测)/255` 的换算成立；
   模拟下午那条分段的亮度结构（极差 83）对齐后**实测极差 1.0**。
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest
from imageio_ffmpeg import get_ffmpeg_exe

from onetake_api.integrations.media.exposure_align import (
    DEFAULT_THRESHOLD,
    MAX_BRIGHTNESS_DELTA,
    align_clip_exposures,
    brightness_filter,
    measure_mean_luma,
    plan_exposure_alignment,
    reencode_with_brightness,
)
from onetake_api.integrations.media.video_utils import VideoProcessingError


# ---------- 1) 纯逻辑 ----------

def test_no_drift_returns_all_zeros() -> None:
    assert plan_exposure_alignment([70.0, 75.0, 80.0]) == [0.0, 0.0, 0.0]


def test_threshold_boundary_is_inclusive() -> None:
    assert plan_exposure_alignment([60.0, 60.0 + DEFAULT_THRESHOLD]) == [0.0, 0.0]
    assert any(plan_exposure_alignment([60.0, 61.0 + DEFAULT_THRESHOLD]))


def test_drift_converges_toward_median() -> None:
    """复刻下午那条分段的四段亮度：偏暗的提亮、最亮的压暗，且修正量与偏离同向。"""
    deltas = plan_exposure_alignment([68.5, 64.5, 132.2, 77.9])
    assert deltas[0] > 0 and deltas[1] > 0
    assert deltas[2] < 0 and deltas[3] < 0
    assert abs(deltas[2]) > abs(deltas[0]) > 0
    assert deltas[2] == pytest.approx(-0.2314, abs=1e-3)
    assert max(abs(item) for item in deltas) <= MAX_BRIGHTNESS_DELTA


def test_extreme_outlier_is_clamped_to_max_delta() -> None:
    deltas = plan_exposure_alignment([0.0, 255.0])
    assert deltas[0] == MAX_BRIGHTNESS_DELTA
    assert deltas[1] == -MAX_BRIGHTNESS_DELTA


def test_tiny_delta_is_zeroed() -> None:
    """半格灰阶的修正不可见 → 归零；真正需要修的那段照旧。"""
    deltas = plan_exposure_alignment([100.0, 100.5, 100.0, 125.0])
    assert deltas[1] == 0.0
    assert deltas[3] < 0


def test_single_or_empty_input_is_noop() -> None:
    assert plan_exposure_alignment([70.0]) == [0.0]
    assert plan_exposure_alignment([]) == []


def test_brightness_filter_skips_zero_and_formats_rest() -> None:
    assert brightness_filter(0.0) is None
    assert brightness_filter(0.0425) == "eq=brightness=0.0425"
    assert brightness_filter(-0.12) == "eq=brightness=-0.1200"


# ---------- 2) 注入假实现 ----------

def test_no_drift_does_not_reencode_anything() -> None:
    clips = [b"clip-a", b"clip-b"]
    calls: list[float] = []
    result = align_clip_exposures(
        clips, measure=lambda _clip: 70.0, reencode=lambda _clip, *, brightness: calls.append(brightness) or b"x"
    )
    assert result.applied is False
    assert calls == []
    assert result.clips == clips


def test_drift_reencodes_every_clip_even_when_delta_is_zero() -> None:
    """触发时必须**每一段**都重编码（含修正量为 0 的段），保证 concat 的输入参数一致。"""
    means = {b"a": 60.0, b"b": 100.0, b"c": 160.0}
    seen: list[tuple[bytes, float]] = []

    def reencode(clip: bytes, *, brightness: float) -> bytes:
        seen.append((clip, brightness))
        return clip + b"-aligned"

    result = align_clip_exposures([b"a", b"b", b"c"], measure=lambda clip: means[clip], reencode=reencode)
    assert result.applied is True
    assert [clip for clip, _ in seen] == [b"a", b"b", b"c"]
    assert [brightness for _, brightness in seen] == result.deltas
    assert result.deltas[1] == 0.0
    assert all(clip.endswith(b"-aligned") for clip in result.clips)
    assert result.spread_after < result.spread_before


def test_single_clip_is_never_measured_or_reencoded() -> None:
    measured: list[int] = []
    result = align_clip_exposures(
        [b"only"],
        measure=lambda _clip: measured.append(1) or 70.0,
        reencode=lambda _clip, *, brightness: b"x",
    )
    assert result.applied is False
    assert measured == []


def test_measurement_failure_propagates_to_caller() -> None:
    def boom(_clip: bytes) -> float:
        raise VideoProcessingError("曝光对齐：亮度测量没有取到样本")

    with pytest.raises(VideoProcessingError):
        align_clip_exposures([b"a", b"b"], measure=boom, reencode=lambda _clip, *, brightness: b"x")


# ---------- 3) 真 ffmpeg 冒烟 ----------

def _solid_clip(color: str, *, seconds: float = 1.0) -> bytes:
    with tempfile.TemporaryDirectory() as temp_dir:
        target = Path(temp_dir) / "clip.mp4"
        subprocess.run(
            [
                get_ffmpeg_exe(), "-y", "-f", "lavfi", "-i", f"color=c={color}:s=320x240:d={seconds}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "24", str(target),
            ],
            check=True, capture_output=True,
        )
        return target.read_bytes()


def test_real_measurement_matches_calibrated_value() -> None:
    assert measure_mean_luma(_solid_clip("0x404040")) == pytest.approx(71.0, abs=3.0)


def test_real_brightness_direction_is_positive_up() -> None:
    base = _solid_clip("0x404040")
    origin = measure_mean_luma(base)
    assert measure_mean_luma(reencode_with_brightness(base, brightness=0.1)) > origin
    assert measure_mean_luma(reencode_with_brightness(base, brightness=-0.1)) < origin


def test_real_alignment_collapses_the_observed_spread() -> None:
    """模拟下午那条分段的亮度结构：对齐前极差 83 → 对齐后实测收敛到个位数。"""
    clips = [
        _solid_clip("0x404040"), _solid_clip("0x303030"),
        _solid_clip("0x909090"), _solid_clip("0x505050"),
    ]
    result = align_clip_exposures(clips)
    assert result.applied is True
    assert result.spread_before == pytest.approx(83.0, abs=5.0)
    after = [measure_mean_luma(clip) for clip in result.clips]
    spread_after = max(after) - min(after)
    assert spread_after <= 10.0
    assert spread_after < result.spread_before / 5
