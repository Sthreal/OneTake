"""AIGC 标识校验（Phase 5）。

标识由本地合成层烧录（见总体方案 §9.2.1），这里负责**断言它真的在画面上**：
在配置的位置抽一帧，统计该区域的高对比像素占比——文字与描边会产生明显边缘，
纯背景则几乎没有。缺失判 fail（这是平台合规项，不是风格选项）。
"""
from __future__ import annotations

import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe
from PIL import Image, ImageFilter, ImageStat

from onetake_api.integrations.media.aigc_label import resolve_position
from onetake_api.platform.errors import DomainError

MIN_EDGE_RATIO = 0.004


class LabelCheckError(DomainError):
    code = "AIGC_LABEL_CHECK_FAILED"
    http_status = 502
    retryable = True


def label_box(
    *, width: int, height: int, position: str, size_ratio: float, margin_ratio: float, avoid_subtitle: bool
) -> tuple[int, int, int, int]:
    resolved = resolve_position(position=position, avoid_subtitle=avoid_subtitle)
    font_size = max(12, int(width * size_ratio))
    # 文案最长按"AI生成内容"6 字估算，留 1.6 倍余量
    box_width = int(font_size * 6 * 1.6)
    box_height = int(font_size * 3)
    margin = int(width * margin_ratio)
    if resolved in {"top_right", "bottom_right"}:
        left = max(0, width - margin - box_width)
    else:
        left = max(0, margin - font_size)
    top = margin - font_size if resolved.startswith("top") else max(0, height - margin - box_height)
    return (left, top, min(width, left + box_width), min(height, top + box_height))


def assert_aigc_label(
    video_bytes: bytes,
    *,
    width: int,
    height: int,
    position: str = "top_right",
    size_ratio: float = 0.028,
    margin_ratio: float = 0.04,
    avoid_subtitle: bool = True,
    at_seconds: float = 1.0,
) -> tuple[bool, str]:
    if not video_bytes:
        raise LabelCheckError("标识校验输入为空")
    box = label_box(
        width=width, height=height, position=position, size_ratio=size_ratio,
        margin_ratio=margin_ratio, avoid_subtitle=avoid_subtitle,
    )
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        video_path = root / "input.mp4"
        frame_path = root / "frame.png"
        video_path.write_bytes(video_bytes)
        command = [
            get_ffmpeg_exe(), "-y", "-ss", f"{max(0.0, at_seconds):.3f}", "-i", str(video_path),
            "-frames:v", "1", str(frame_path),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, errors="replace")
        except (subprocess.CalledProcessError, OSError) as exc:
            raise LabelCheckError("标识校验抽帧失败") from exc
        if not frame_path.is_file():
            raise LabelCheckError("标识校验抽帧为空")
        with Image.open(BytesIO(frame_path.read_bytes())) as image:
            region = image.convert("L").crop(box)
    edges = region.filter(ImageFilter.FIND_EDGES).point(lambda value: 255 if value >= 24 else 0)
    histogram = edges.histogram()
    ratio = histogram[255] / max(1, region.width * region.height)
    contrast = ImageStat.Stat(region).stddev[0]
    if ratio >= MIN_EDGE_RATIO and contrast >= 6:
        return True, f"标识区域检出文字（边缘占比 {ratio:.1%}）"
    return False, f"标识区域未检出文字（边缘占比 {ratio:.1%}，对比 {contrast:.1f}）"