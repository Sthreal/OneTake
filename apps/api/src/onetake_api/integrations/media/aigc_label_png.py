"""AIGC 标识的位图渲染（S6：容器内通用实现）。

**为什么存在**：容器镜像里的 `imageio-ffmpeg` 静态构建缺 `--enable-libfreetype`，
`drawtext` 滤镜**不存在**，原实现（drawtext）在容器内必然抛错 → `LocalCompositionAdapter`
不捕获 `AigcLabelError` → **整条合成失败、成片产不出来**（默认 `AIGC_LABEL_ENABLED=true`）。

**怎么做**：把"画字"从 ffmpeg 挪到 Pillow，输出**与视频同尺寸的全帧 RGBA 透明 PNG**，
再由 ffmpeg 用 `overlay` 合成 —— `overlay` 是核心滤镜，任何构建都有。

**等价性约束**（与 drawtext 版本逐项对齐，做到"零观感变化"）：
- 字号 `max(12, int(width * clamp(size_ratio, 0.01, 0.1)))` —— 与 drawtext 完全一致
- 边距 `max(0, int(width * clamp(margin_ratio, 0.0, 0.2)))` —— 与 drawtext 完全一致
- 白色文字 + **2px 黑色描边**（对应 `borderw=2`），描边不透明度 = `alpha * 0.6`
- 定位与 drawtext 的 x/y 表达式逐字对应；`text_w/text_h` 指**未加描边**的文字框，
  描边允许向外溢出 2px —— 这正是 drawtext 的行为

纯函数、零 I/O（字体只读一次并缓存），便于单测。
"""
from __future__ import annotations

from functools import lru_cache
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from onetake_api.integrations.media.subtitle_burner import CAPTION_FONT_PATH

POSITIONS = ("top_right", "top_left", "bottom_right", "bottom_left")
DEFAULT_POSITION = "top_right"

# 对应 drawtext 的 borderw=2：黑色描边向外溢出 2px
STROKE_WIDTH = 2
# 对应 drawtext 的 bordercolor=black@{alpha * 0.6}
STROKE_OPACITY_RATIO = 0.6
_TEXT_RGB = (255, 255, 255)
_STROKE_RGB = (0, 0, 0)


class AigcLabelRenderError(ValueError):
    """位图渲染入参非法（纯函数层，不依赖 DomainError）。"""


def resolve_font_size(width: int, size_ratio: float) -> int:
    """与 drawtext 版一致：宽度比例夹紧在 [0.01, 0.1]，下限 12px。"""
    return max(12, int(width * max(0.01, min(0.1, size_ratio))))


def resolve_margin(width: int, margin_ratio: float) -> int:
    """与 drawtext 版一致：边距比例夹紧在 [0.0, 0.2]。"""
    return max(0, int(width * max(0.0, min(0.2, margin_ratio))))


def label_origin(
    position: str, *, width: int, height: int, text_w: int, text_h: int, margin: int
) -> tuple[int, int]:
    """文字框左上角坐标；与 drawtext 的 x/y 表达式逐字对应。"""
    if position == "top_left":
        return margin, margin
    if position == "bottom_right":
        return width - text_w - margin, height - text_h - margin
    if position == "bottom_left":
        return margin, height - text_h - margin
    if position == "top_right":
        return width - text_w - margin, margin
    raise AigcLabelRenderError(f"未知标识位置：{position}")


@lru_cache(maxsize=16)
def _load_font(font_size: int) -> ImageFont.FreeTypeFont:
    if not CAPTION_FONT_PATH.is_file():
        raise AigcLabelRenderError("中文字体资源缺失")
    return ImageFont.truetype(str(CAPTION_FONT_PATH), font_size)


def _text_box(text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int, int, int]:
    """未加描边的文字外框 (left, top, right, bottom)。

    用**未加描边**的外框做定位，是为了复现 drawtext 的 `text_w`/`text_h` 口径
    （描边允许向外溢出 2px，不参与定位）。
    """
    draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    return draw.textbbox((0, 0), text, font=font)


def build_label_overlay_png(
    *,
    text: str,
    width: int,
    height: int,
    position: str = DEFAULT_POSITION,
    size_ratio: float = 0.028,
    opacity: float = 0.75,
    margin_ratio: float = 0.04,
) -> bytes:
    """渲染 AIGC 标识为**全帧 RGBA 透明 PNG**（可直接给 ffmpeg `overlay=0:0`）。"""
    if not text or not text.strip():
        raise AigcLabelRenderError("AIGC 标识文案为空")
    if width <= 0 or height <= 0:
        raise AigcLabelRenderError("AIGC 标识画布尺寸非法")
    if position not in POSITIONS:
        raise AigcLabelRenderError(f"未知标识位置：{position}")

    font_size = resolve_font_size(width, size_ratio)
    margin = resolve_margin(width, margin_ratio)
    alpha = max(0.0, min(1.0, opacity))
    font = _load_font(font_size)

    left, top, right, bottom = _text_box(text, font)
    text_w, text_h = right - left, bottom - top
    x, y = label_origin(position, width=width, height=height, text_w=text_w, text_h=text_h, margin=margin)

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.text(
        (x - left, y - top),
        text,
        font=font,
        fill=(*_TEXT_RGB, round(255 * alpha)),
        stroke_width=STROKE_WIDTH,
        stroke_fill=(*_STROKE_RGB, round(255 * alpha * STROKE_OPACITY_RATIO)),
    )

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()