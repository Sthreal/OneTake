"""拼接前的「跨段曝光对齐」（S1）。

**为什么要有它**：分段路径是 **N 次独立生成** —— 每段各自决定曝光与色调，代码里没有任何跨段
一致性约束。实测（2026-10-15，18s / 4 段 / `vid_6eec1c64…`）：四条片段的平均亮度 YAVG 分别是
**68.5 / 64.5 / 132.2 / 77.9**（最亮 = 最暗的 2 倍），成片观感就是"忽明忽暗、发暗发灰"。
对照同一批次的一次成片（`one_shot`）：全程 100–161，稳定。

**做法刻意保守**（四条纪律，逐条都有测试钉住）：

1. **只在检测到漂移时才动手**：极差 ≤ `DEFAULT_THRESHOLD` → 原样返回，**零重编码**；
2. **修正量有硬上限**：`MAX_BRIGHTNESS_DELTA`（±0.25 ≈ ±64/255）—— 宁可修不到目标，也不把画面拉爆；
3. **触发时所有片段一律重编码**（同样的编码参数）：避免"部分 provider 原生 + 部分 libx264"
   混在一起喂给 concat 解复用器；拼接路径本来就丢弃片段音轨（`keep_audio=False`），所以这里
   统一输出视频流（`-an`）；
4. **纯逻辑与 ffmpeg 分离**：阈值判定与修正量计算是纯函数，测量/重编码可注入 → 单测不需要 ffmpeg。

**已知边界**：`eq=brightness` 的映射是近似线性的（有限量程 YUV 上略有非线性），所以本模块给出的
`spread_after` 是**估算值**；真实收敛程度由 `tests/unit/test_exposure_align.py` 的真 ffmpeg 冒烟用例
测出来（不是假设）。
"""
from __future__ import annotations

import re
import statistics
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

from onetake_api.integrations.media.video_utils import VideoProcessingError

# 极差 ≤ 此值视为"本来就在同一个曝光区间"，不做任何处理（实测正常同批次片段极差 < 15）
DEFAULT_THRESHOLD = 20.0
# 单段允许的最大修正（≈ ±64/255）。实测定标：最坏那次需要 -0.231 才能追上中位数，
# 因此上限取 0.25 —— 够用于已知最坏情况，又远小于 1.0（=纯白）这种破坏性修正。
MAX_BRIGHTNESS_DELTA = 0.25
# 小于 1/255 的修正没有可见意义，归零（同时让"哪几段真的被改了"可读）
MIN_APPLIED_DELTA = 0.004
# 测量采样率：2 帧/秒足够稳定（整段均值），又比逐帧快一个量级
DEFAULT_SAMPLE_FPS = 2.0

# ffmpeg `metadata=print` 的输出形如 `lavfi.signalstats.YAVG=68.51`
_YAVG_RE = re.compile(r"lavfi\.signalstats\.YAVG=([\d.]+)")


@dataclass(frozen=True)
class ExposureAlignment:
    """一次对齐的结果。`applied=False` 时 `clips` 与输入**逐字节相同**。"""

    clips: list[bytes] = field(default_factory=list)
    means: list[float] = field(default_factory=list)
    deltas: list[float] = field(default_factory=list)
    applied: bool = False
    spread_before: float = 0.0
    spread_after: float = 0.0


def plan_exposure_alignment(
    means: Sequence[float],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    max_delta: float = MAX_BRIGHTNESS_DELTA,
) -> list[float]:
    """纯函数：每段平均亮度 → 每段要加的 `eq=brightness` 值（0.0 = 不动）。

    目标取**中位数**（而不是均值）：一段极亮或极暗的片不该把整片的基调拽走。
    """
    if len(means) < 2:
        return [0.0] * len(means)
    ordered = sorted(float(value) for value in means)
    if ordered[-1] - ordered[0] <= threshold:
        return [0.0] * len(means)
    target = float(statistics.median(ordered))
    deltas: list[float] = []
    for mean in means:
        raw = (target - float(mean)) / 255.0
        if abs(raw) < MIN_APPLIED_DELTA:
            raw = 0.0
        deltas.append(round(max(-max_delta, min(max_delta, raw)), 4))
    return deltas


def brightness_filter(value: float) -> str | None:
    """修正量为 0 时返回 None（调用方据此跳过重编码）。"""
    if not value:
        return None
    return f"eq=brightness={value:.4f}"


def measure_mean_luma(video_bytes: bytes, *, sample_fps: float = DEFAULT_SAMPLE_FPS) -> float:
    """测一段视频的平均亮度（YAVG，0–255）。测量失败抛 `VideoProcessingError`，不返回猜测值。"""
    if not video_bytes:
        raise VideoProcessingError("曝光对齐：片段为空")
    with tempfile.TemporaryDirectory() as temp_dir:
        source = Path(temp_dir) / "clip.mp4"
        source.write_bytes(video_bytes)
        command = [
            get_ffmpeg_exe(), "-hide_banner", "-nostats", "-i", str(source),
            "-vf", f"fps={sample_fps},signalstats,metadata=print:key=lavfi.signalstats.YAVG",
            "-f", "null", "-",
        ]
        try:
            completed = subprocess.run(command, check=False, capture_output=True, text=True)
        except OSError as exc:
            raise VideoProcessingError("曝光对齐：亮度测量无法执行") from exc
        values = [float(value) for value in _YAVG_RE.findall(completed.stderr)]
        if not values:
            raise VideoProcessingError("曝光对齐：亮度测量没有取到样本")
        return sum(values) / len(values)


def reencode_with_brightness(
    video_bytes: bytes, *, brightness: float, crf: int = 18, preset: str = "veryfast"
) -> bytes:
    """按给定修正量重编码（纯视频流，与拼接路径 `keep_audio=False` 一致）。"""
    if not video_bytes:
        raise VideoProcessingError("曝光对齐：片段为空")
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source = root / "in.mp4"
        target = root / "out.mp4"
        source.write_bytes(video_bytes)
        command = [get_ffmpeg_exe(), "-y", "-i", str(source), "-an"]
        expression = brightness_filter(brightness)
        if expression:
            command += ["-vf", expression]
        command += [
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p", str(target),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except (subprocess.CalledProcessError, OSError) as exc:
            raise VideoProcessingError("曝光对齐：重编码失败") from exc
        if not target.is_file() or target.stat().st_size == 0:
            raise VideoProcessingError("曝光对齐：重编码结果为空")
        return target.read_bytes()


def align_clip_exposures(
    clips: Sequence[bytes],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    max_delta: float = MAX_BRIGHTNESS_DELTA,
    measure: Callable[[bytes], float] | None = None,
    reencode: Callable[..., bytes] | None = None,
) -> ExposureAlignment:
    """按需对齐一组片段的曝光。

    - 极差 ≤ `threshold`：`applied=False`，**不调用重编码**（逐字节返回原片段）；
    - 触发时：**每一段**都重编码（含修正量为 0 的段），保证喂给 concat 的输入参数一致。
    """
    measure = measure or measure_mean_luma
    reencode = reencode or reencode_with_brightness
    originals = list(clips)
    if len(originals) < 2:
        return ExposureAlignment(clips=originals, means=[], deltas=[0.0] * len(originals))

    means = [float(measure(clip)) for clip in originals]
    spread_before = max(means) - min(means)
    deltas = plan_exposure_alignment(means, threshold=threshold, max_delta=max_delta)
    if not any(deltas):
        return ExposureAlignment(clips=originals, means=means, deltas=deltas, spread_before=spread_before, spread_after=spread_before)

    adjusted = [reencode(clip, brightness=delta) for clip, delta in zip(originals, deltas)]
    estimated = [mean + delta * 255.0 for mean, delta in zip(means, deltas)]
    return ExposureAlignment(
        clips=adjusted,
        means=means,
        deltas=deltas,
        applied=True,
        spread_before=spread_before,
        spread_after=max(estimated) - min(estimated),
    )
