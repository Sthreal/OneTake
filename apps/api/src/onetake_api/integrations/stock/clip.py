"""素材片段的下载与归一化（批次 4a）。

素材平台的视频**不能直接当分段视频用**：尺寸、时长、帧率、编码、音轨都可能不同。
这里做"下载 → 归一化（铺满裁切 + 循环补足时长 + 静音 + H.264）→ 抽首尾帧"三件事，
产物形状与 `SegmentVideoGenerator` 的 `GeneratedCandidate` 一致，所以能直接接进既有管线。
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

from onetake_api.integrations.media.video_utils import (
    extract_head_frame,
    extract_tail_frame,
    inspect_video_dimensions,
    inspect_video_duration,
)
from onetake_api.integrations.stock import http
from onetake_api.integrations.stock.domain import StockAsset, StockError

MAX_ASSET_BYTES = 40 * 1024 * 1024
TAIL_OFFSET_FRAMES = 2


def download_asset(asset: StockAsset, *, client=None, max_bytes: int = MAX_ASSET_BYTES) -> bytes:
    try:
        content = http.get_bytes(url=asset.download_url, client=client, max_bytes=max_bytes)
    except Exception as exc:  # noqa: BLE001 - 网络层的任何失败都归为"素材拿不到"，由调用方回退
        raise StockError(f"素材下载失败：{asset.title}") from exc
    if not content:
        raise StockError(f"素材下载为空：{asset.title}")
    return content


def normalize_clip(
    *, source_bytes: bytes, duration_seconds: float, width: int, height: int, fps: int
) -> bytes:
    """铺满裁切到目标规格 + 循环补足时长 + 去音轨 + H.264；产物**自检**不通过就报错。"""
    if not source_bytes:
        raise StockError("素材片段为空")
    target = max(0.1, float(duration_seconds))
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_path = root / "source.bin"
        output_path = root / "clip.mp4"
        source_path.write_bytes(source_bytes)
        command = [
            get_ffmpeg_exe(), "-y",
            # 素材通常比目标时长短 → 循环；末尾由 -t 截断
            "-stream_loop", "-1", "-i", str(source_path),
            "-an",
            "-vf", (
                f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},setsar=1,fps={fps}"
            ),
            "-t", f"{target:.3f}",
            "-c:v", "libx264", "-b:v", "8M", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(output_path),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except (subprocess.CalledProcessError, OSError) as exc:
            raise StockError("素材归一化失败") from exc
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise StockError("素材归一化输出为空")
        normalized = output_path.read_bytes()
    try:
        actual_width, actual_height = inspect_video_dimensions(normalized)
        actual_seconds = inspect_video_duration(normalized)
    except Exception as exc:  # noqa: BLE001 - 自检失败一律当素材不可用
        raise StockError("素材归一化结果无法解析") from exc
    if (actual_width, actual_height) != (width, height):
        raise StockError(f"素材归一化尺寸 {actual_width}x{actual_height} 与目标 {width}x{height} 不一致")
    if abs(actual_seconds - target) > 0.2:
        raise StockError(f"素材归一化时长 {actual_seconds:.3f}s 与目标 {target:.3f}s 不一致")
    return normalized


def head_and_tail_frames(video_bytes: bytes) -> tuple[bytes, bytes]:
    """首帧 + 尾帧（尾帧沿用生产同一口径：倒数第 2 帧），供下一段续写当锚点。"""
    try:
        return extract_head_frame(video_bytes), extract_tail_frame(video_bytes, offset_frames=TAIL_OFFSET_FRAMES)
    except Exception as exc:  # noqa: BLE001
        raise StockError("素材片段首尾帧抽取失败") from exc