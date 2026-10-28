"""S6 单测：AIGC 标识的位图渲染（纯 Pillow，不依赖 ffmpeg，宿主机与容器内结果一致）。"""
from __future__ import annotations

import pytest
from PIL import Image

from onetake_api.integrations.media.aigc_label_png import (
    DEFAULT_POSITION,
    POSITIONS,
    STROKE_WIDTH,
    AigcLabelRenderError,
    build_label_overlay_png,
    label_origin,
    resolve_font_size,
    resolve_margin,
)

WIDTH, HEIGHT = 1080, 1920
# 与 config.py 的默认值一致：AIGC_LABEL_SIZE_RATIO=0.028 / SAFE_MARGIN_RATIO=0.04
DEFAULT_FONT_SIZE = 30  # 1080 × 0.028 ≈ 30.24 → 30
DEFAULT_MARGIN = 43  # 1080 × 0.04 = 43.2 → 43


def _png(**overrides) -> bytes:
    params = {"text": "AI生成", "width": WIDTH, "height": HEIGHT}
    params.update(overrides)
    return build_label_overlay_png(**params)


def _ink_box(png: bytes) -> tuple[int, int, int, int] | None:
    with Image.open(__import__("io").BytesIO(png)) as image:
        return image.convert("RGBA").getchannel("A").getbbox()


# ---- 与 drawtext 版逐项等价的纯函数 ----


def test_resolve_font_size_and_margin_match_drawtext_contract() -> None:
    # 与旧 drawtext 实现完全相同的算式（1080 宽 + 默认比例）
    assert resolve_font_size(WIDTH, 0.028) == DEFAULT_FONT_SIZE
    assert resolve_margin(WIDTH, 0.04) == DEFAULT_MARGIN
    # 夹紧：size_ratio ∈ [0.01, 0.1]，下限 12px
    assert resolve_font_size(200, 0.028) == 12          # 200×0.028=5.6 → 夹到 12
    assert resolve_font_size(2000, 1.0) == 200          # 夹到 0.1
    assert resolve_font_size(2000, 0.0) == 20           # 夹到 0.01
    # 夹紧：margin_ratio ∈ [0.0, 0.2]
    assert resolve_margin(2000, 1.0) == 400
    assert resolve_margin(1080, -1.0) == 0


def test_label_origin_matches_drawtext_position_expressions() -> None:
    """drawtext 的 x/y 表达式逐字对应：w-text_w-{m} / {m} / h-text_h-{m}。"""
    origin = lambda pos: label_origin(pos, width=WIDTH, height=HEIGHT, text_w=100, text_h=30, margin=DEFAULT_MARGIN)
    assert origin("top_right") == (WIDTH - 100 - DEFAULT_MARGIN, DEFAULT_MARGIN)
    assert origin("top_left") == (DEFAULT_MARGIN, DEFAULT_MARGIN)
    assert origin("bottom_right") == (WIDTH - 100 - DEFAULT_MARGIN, HEIGHT - 30 - DEFAULT_MARGIN)
    assert origin("bottom_left") == (DEFAULT_MARGIN, HEIGHT - 30 - DEFAULT_MARGIN)


def test_label_origin_rejects_unknown_position() -> None:
    with pytest.raises(AigcLabelRenderError):
        label_origin("middle", width=WIDTH, height=HEIGHT, text_w=10, text_h=10, margin=0)


# ---- 位图本身 ----


def test_overlay_png_is_full_frame_rgba() -> None:
    png = _png()
    with Image.open(__import__("io").BytesIO(png)) as image:
        assert image.size == (WIDTH, HEIGHT)     # 全帧尺寸（overlay 要求与视频同尺寸）
        assert image.mode == "RGBA"              # 必须带 alpha，否则 overlay 会盖住整幅画面
        assert image.mode == "RGBA" and "A" in image.getbands()


@pytest.mark.parametrize("position", POSITIONS)
def test_overlay_png_ink_sits_in_the_requested_corner_with_drawtext_bleed(position: str) -> None:
    """四条位置各验一次：文字真的画上了，且落在指定角落、外沿与 drawtext 一致。

    drawtext 的行为是「文字框右/下沿贴在 margin 处，2px 描边向外溢出」——
    位图版必须复现这一点（`±STROKE_WIDTH` 即溢出量）。
    """
    box = _ink_box(_png(position=position))
    assert box is not None, "标识未画出任何可见像素"
    x0, y0, x1, y1 = box
    left_half, top_half = WIDTH // 2, HEIGHT // 2
    tolerance = STROKE_WIDTH

    if position == "top_right":
        assert x0 > left_half and y1 < top_half
        assert abs(x1 - (WIDTH - DEFAULT_MARGIN)) <= tolerance     # 右沿溢出 margin 外 2px
        assert abs(y0 - (DEFAULT_MARGIN - STROKE_WIDTH)) <= 1      # 上沿溢出 2px
    elif position == "top_left":
        assert x1 < left_half and y1 < top_half
        assert abs(x0 - (DEFAULT_MARGIN - STROKE_WIDTH)) <= 1
        assert abs(y0 - (DEFAULT_MARGIN - STROKE_WIDTH)) <= 1
    elif position == "bottom_right":
        assert x0 > left_half and y0 > top_half
        assert abs(x1 - (WIDTH - DEFAULT_MARGIN)) <= tolerance
        assert abs(y1 - (HEIGHT - DEFAULT_MARGIN + STROKE_WIDTH)) <= tolerance
    else:  # bottom_left
        assert x1 < left_half and y0 > top_half
        assert abs(x0 - (DEFAULT_MARGIN - STROKE_WIDTH)) <= 1
        assert abs(y1 - (HEIGHT - DEFAULT_MARGIN + STROKE_WIDTH)) <= tolerance


def test_overlay_png_renders_cjk_and_honours_opacity() -> None:
    """中文不能丢字（画不出字 = 合规标识形同虚设）；透明度要落到 alpha 通道上。"""
    box = _ink_box(_png(text="AI生成"))
    ascii_only = _ink_box(_png(text="AI"))
    assert box is not None and ascii_only is not None
    x0, y0, x1, y1 = box
    ascii_x0, _, ascii_x1, _ = ascii_only
    # 汉字必须真的画出来：加上「生成」两个汉字后，宽度至少再加一个字号的宽度
    assert (x1 - x0) > (ascii_x1 - ascii_x0) + DEFAULT_FONT_SIZE
    assert y1 - y0 >= DEFAULT_FONT_SIZE * 0.5    # 有实际字高（不是空白图）

    with Image.open(__import__("io").BytesIO(_png(opacity=0.5))) as image:
        alpha = image.convert("RGBA").getchannel("A")
        assert max(alpha.getdata()) == round(255 * 0.5)      # 文字本体 = alpha
        assert min(alpha.getdata()) == 0                     # 背景必须完全透明


def test_overlay_png_default_position_is_top_right() -> None:
    assert DEFAULT_POSITION == "top_right"
    assert _ink_box(_png()) == _ink_box(_png(position="top_right"))


def test_overlay_png_rejects_invalid_input() -> None:
    with pytest.raises(AigcLabelRenderError):
        _png(text="   ")
    with pytest.raises(AigcLabelRenderError):
        _png(text="")
    with pytest.raises(AigcLabelRenderError):
        _png(position="middle")
    with pytest.raises(AigcLabelRenderError):
        _png(width=0)