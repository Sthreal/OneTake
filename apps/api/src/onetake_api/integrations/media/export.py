"""多平台导出（批次 6）：**复用容器内已有的 crop / scale / gblur**，不覆盖原片。

三种处理策略（都由 profile 决定，不在这里猜）：

| 策略 | 做什么 | 什么时候用 |
|---|---|---|
| `passthrough` | 目标规格 == 原片规格 → **流拷贝**（不重编码，零损失、最快）；规格不一致 → 等比缩放 + 黑边（不裁切） | 抖音 / 视频号 / TikTok（9:16 就是原片） |
| `blur_pad` | 模糊背景留白：原片放大模糊铺满画布，前景等比缩放居中 | 小红书 3:4（**不丢任何画面**） |
| `center_crop` | 居中裁切铺满：把 9:16 裁成 3:4（**会切掉上下各 12.5%**） | 可选（配置切换），适合主体居中的画面 |

`measure()` 给出**实测**尺寸/时长/码率/有无音轨 —— 导出报告用的是实测值，不是"按参数推断"。
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

from onetake_api.integrations.media.video_utils import inspect_video_dimensions, inspect_video_duration
from onetake_api.platform.errors import DomainError

STRATEGY_PASSTHROUGH = "passthrough"
# 规格不一致时的兜底：等比缩放 + 黑边（**绝不裁切**：这是"原样"策略的底线）
PASSTHROUGH_PAD_RATIO = "decrease"
STRATEGY_BLUR_PAD = "blur_pad"
STRATEGY_CENTER_CROP = "center_crop"
STRATEGIES = frozenset({STRATEGY_PASSTHROUGH, STRATEGY_BLUR_PAD, STRATEGY_CENTER_CROP})
BLUR_SIGMA = 22
VIDEO_BITRATE = "8M"
COVER_QUALITY = 2


class ExportError(DomainError):
    code = "VIDEO_EXPORT_FAILED"
    http_status = 502
    retryable = True


@dataclass(frozen=True)
class ExportMeasurement:
    width: int
    height: int
    duration_seconds: float
    size_bytes: int
    has_audio: bool

    @property
    def bitrate_kbps(self) -> int:
        if self.duration_seconds <= 0:
            return 0
        return int(round(self.size_bytes * 8 / self.duration_seconds / 1000))


def build_reframe_filter(*, strategy: str, width: int, height: int, fps: int | None = None) -> str:
    """纯函数：策略 → 滤镜串（单测直接断言字符串，不必真渲染）。

    `fps=None` 表示"不插 fps 滤镜"——单帧（封面）路径用它，视频路径必须给帧率。
    """
    tail = f",fps={fps}" if fps else ""
    if strategy == STRATEGY_BLUR_PAD:
        return (
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},gblur=sigma={BLUR_SIGMA}[bg];"
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2:format=auto{tail},setsar=1[out]"
        )
    if strategy == STRATEGY_CENTER_CROP:
        return (
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}{tail},setsar=1[out]"
        )
    if strategy == STRATEGY_PASSTHROUGH:
        # 目标规格与原片不一致时的兜底：等比缩放 + 黑边（**不裁不拉**）
        return (
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio={PASSTHROUGH_PAD_RATIO},"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black{tail},setsar=1[out]"
        )
    raise ExportError(f"未知导出策略：{strategy}")


def export_video(
    *, source_bytes: bytes, strategy: str, width: int, height: int, fps: int
) -> bytes:
    """按策略导出；`passthrough` 走流拷贝（不重编码），其余重新编码。"""
    if not source_bytes:
        raise ExportError("导出输入为空")
    if strategy not in STRATEGIES:
        raise ExportError(f"未知导出策略：{strategy}")
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_path = root / "source.mp4"
        output_path = root / "export.mp4"
        source_path.write_bytes(source_bytes)
        source_measure = measure(source_bytes)
        same_spec = (source_measure.width, source_measure.height) == (width, height)
        if strategy == STRATEGY_PASSTHROUGH and same_spec:
            # 规格一致 → 流拷贝：不重编码、零损失、最快
            command = [
                get_ffmpeg_exe(), "-y", "-i", str(source_path),
                "-c", "copy", "-movflags", "+faststart", str(output_path),
            ]
        else:
            command = [
                get_ffmpeg_exe(), "-y", "-i", str(source_path),
                "-filter_complex", build_reframe_filter(strategy=strategy, width=width, height=height, fps=fps),
                "-map", "[out]", "-map", "0:a?",
                "-c:v", "libx264", "-b:v", VIDEO_BITRATE, "-pix_fmt", "yuv420p",
                "-c:a", "copy", "-movflags", "+faststart", str(output_path),
            ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except (subprocess.CalledProcessError, OSError) as exc:
            raise ExportError("导出转码失败") from exc
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise ExportError("导出输出为空")
        exported = output_path.read_bytes()
    measured = measure(exported)
    if (measured.width, measured.height) != (width, height):
        raise ExportError(f"导出规格 {measured.width}x{measured.height} 与目标 {width}x{height} 不一致")
    return exported


def export_frame(*, source_bytes: bytes, at_seconds: float, strategy: str, width: int, height: int) -> bytes:
    """单帧导出（封面 / 构图预览）：先抽帧，再按策略折到目标画幅，最后输出 PNG。"""
    if not source_bytes:
        raise ExportError("封面输入为空")
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_path = root / "source.mp4"
        frame_path = root / "frame.png"
        output_path = root / "cover.png"
        source_path.write_bytes(source_bytes)
        try:
            subprocess.run(
                [get_ffmpeg_exe(), "-y", "-ss", f"{max(0.0, at_seconds):.3f}", "-i", str(source_path),
                 "-frames:v", "1", str(frame_path)],
                check=True, capture_output=True, text=True,
            )
            if strategy == STRATEGY_PASSTHROUGH:
                command = [get_ffmpeg_exe(), "-y", "-i", str(frame_path), "-frames:v", "1", str(output_path)]
            else:
                command = [
                    get_ffmpeg_exe(), "-y", "-i", str(frame_path),
                    "-filter_complex", build_reframe_filter(strategy=strategy, width=width, height=height),
                    "-map", "[out]", "-frames:v", "1", str(output_path),
                ]
            subprocess.run(command, check=True, capture_output=True, text=True)
        except (subprocess.CalledProcessError, OSError) as exc:
            raise ExportError("封面导出失败") from exc
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise ExportError("封面输出为空")
        return output_path.read_bytes()


def measure(video_bytes: bytes) -> ExportMeasurement:
    """**实测**测量（尺寸/时长/有无音轨）——导出报告的"码率"由它算出来，不是从参数推断。"""
    if not video_bytes:
        raise ExportError("测量输入为空")
    try:
        width, height = inspect_video_dimensions(video_bytes)
        duration = inspect_video_duration(video_bytes)
    except Exception as exc:  # noqa: BLE001
        raise ExportError("导出结果无法解析") from exc
    return ExportMeasurement(
        width=width, height=height, duration_seconds=round(float(duration), 3),
        size_bytes=len(video_bytes), has_audio=_has_audio(video_bytes),
    )


def _has_audio(video_bytes: bytes) -> bool:
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "probe.mp4"
        path.write_bytes(video_bytes)
        result = subprocess.run([get_ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    return bool(re.search(r"Stream #\d+:\d+.*: Audio:", result.stderr))