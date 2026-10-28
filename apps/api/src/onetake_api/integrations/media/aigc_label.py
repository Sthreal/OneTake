"""AIGC 标识烧录（本地叠加优先）。

决策依据（总体方案 §9.2.1）：
- 分段生成时每段都调一次模型，**模型自带水印会在同一位置重复闪 N 次**；本地叠加只在最终成片上做一次
- 本地叠加可配置位置/字号/透明度、可与字幕避让、可被 QC 断言
- 必须在 native-feel **之后**执行（否则手抖 crop 会把标识裁掉一部分）

实现方式（S6 改造）：
- 标识先用 `aigc_label_png.build_label_overlay_png()` 以 Pillow 预渲染成
  **与视频同尺寸的全帧 RGBA 透明 PNG**，再由 ffmpeg `overlay` 合成 —— **不再使用 drawtext**。
- 为什么必须换掉 drawtext：容器镜像里的 `imageio-ffmpeg` 静态构建缺 `--enable-libfreetype`，
  `drawtext` 滤镜**不存在**。用它会让 `LocalCompositionAdapter.compose()` 直接抛
  `AigcLabelError`（本模块不吞异常），**整条合成失败、成片产不出来**；而交付门又对
  `aigc_label` 做 fail 级硬断言，所以不能靠"关掉标识"绕过。
- `overlay` 是 ffmpeg 核心滤镜，任何构建都有 → 宿主机与容器内行为一致、零新增依赖。
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

from onetake_api.integrations.media.aigc_label_png import (
    DEFAULT_POSITION,
    POSITIONS,
    build_label_overlay_png,
)
from onetake_api.platform.errors import DomainError

__all__ = [
    "AigcLabelError",
    "DEFAULT_POSITION",
    "POSITIONS",
    "build_label_overlay_png",
    "draw_aigc_label",
    "resolve_position",
]


class AigcLabelError(DomainError):
    code = "VIDEO_POSTPROCESS_ERROR"
    http_status = 502
    retryable = True


def resolve_position(*, position: str, avoid_subtitle: bool) -> str:
    """字幕在下时，把底部的标识自动上移（避免压字）。"""
    if not avoid_subtitle:
        return position
    if position == "bottom_right":
        return "top_right"
    if position == "bottom_left":
        return "top_left"
    return position


def draw_aigc_label(
    video_bytes: bytes,
    *,
    width: int,
    height: int,
    fps: int = 30,
    text: str = "AI生成",
    position: str = DEFAULT_POSITION,
    size_ratio: float = 0.028,
    opacity: float = 0.75,
    margin_ratio: float = 0.04,
    avoid_subtitle: bool = True,
) -> bytes:
    if not video_bytes:
        raise AigcLabelError("AIGC 标识输入为空")
    if not text.strip():
        raise AigcLabelError("AIGC 标识文案为空")
    resolved = resolve_position(position=position, avoid_subtitle=avoid_subtitle)
    try:
        overlay_png = build_label_overlay_png(
            text=text, width=width, height=height, position=resolved,
            size_ratio=size_ratio, opacity=opacity, margin_ratio=margin_ratio,
        )
    except ValueError as exc:
        # AigcLabelRenderError 继承 ValueError：把纯函数层的入参错误翻译成领域错误
        raise AigcLabelError(str(exc)) from exc

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        input_path = root / "input.mp4"
        overlay_path = root / "label.png"
        output_path = root / "output.mp4"
        input_path.write_bytes(video_bytes)
        overlay_path.write_bytes(overlay_png)
        command = [
            get_ffmpeg_exe(), "-y",
            "-i", str(input_path),
            "-i", str(overlay_path),
            # eof_action=repeat 是 overlay 的默认值，这里显式写出以自证意图：
            # 标识是单帧 PNG，必须在整个视频时长内保持显示（否则只闪一帧）
            "-filter_complex", "[0:v][1:v]overlay=0:0:eof_action=repeat[v]",
            "-map", "[v]", "-map", "0:a?",
            "-r", str(fps),
            "-c:v", "libx264", "-b:v", "8M", "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            str(output_path),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except (subprocess.CalledProcessError, OSError) as exc:
            raise AigcLabelError("AIGC 标识烧录失败") from exc
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise AigcLabelError("AIGC 标识输出为空")
        return output_path.read_bytes()