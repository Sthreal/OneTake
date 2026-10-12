from __future__ import annotations

import io

from PIL import Image, ImageDraw

from onetake_api.integrations.mock_matting.adapter import MockMattingAdapter


def _product_on_flat_background() -> bytes:
    image = Image.new("RGB", (600, 600), (245, 245, 245))
    ImageDraw.Draw(image).rounded_rectangle((180, 120, 420, 500), radius=40, fill=(210, 70, 30))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_mock_matting_removes_flat_background() -> None:
    """回归：边缘取样画布只有 1 像素高，左右两条竖边贴不进去，剩下的像素保持初始黑色，
    于是「背景色」被黑色污染、与任何像素的差异都超过阈值 —— 所有像素都被判成商品，
    MOCK_PROVIDERS=true（默认）时去背永远不生效。
    """
    result = MockMattingAdapter().remove_background(image_bytes=_product_on_flat_background())

    with Image.open(io.BytesIO(result)) as image:
        alpha = image.convert("RGBA").getchannel("A")

    total = alpha.width * alpha.height
    transparent = sum(alpha.histogram()[:128]) / total
    assert transparent > 0.5, "纯色背景应该被基本抠掉"
    assert alpha.getpixel((300, 300)) == 255, "商品区域必须保持不透明"
