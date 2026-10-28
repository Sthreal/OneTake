"""pixel-lock 兜底（Phase 1）：生成式关键帧保真不通过时，把原始商品像素贴回画面。

保真三级降级中的第二级：
    integrated（生成入画）→ **pixel-lock（生成场景 + 原始像素回贴）** → erase+overlay（旧路径）

做法刻意保守：
1. 商品按原始像素缩放贴入（不做任何重绘，包装文字 100% 保真）
2. 用场景区域的平均亮度/色偏对商品做**有限**的明暗与色温匹配（factor 限制在 0.92~1.08，避免改色）
3. 叠加接触阴影，避免"悬浮感"
"""
from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageEnhance, ImageOps, ImageStat

from onetake_api.integrations.media.image_utils import add_contact_shadow

DEFAULT_HEIGHT_RATIO = 0.72
DEFAULT_BOTTOM_MARGIN_RATIO = 0.12
MAX_LIGHT_FACTOR = 1.08
MIN_LIGHT_FACTOR = 0.92
DEFAULT_MAX_WIDTH_RATIO = 0.9


def lock_product_pixels(
    *,
    scene_image: bytes,
    product_png: bytes,
    height_ratio: float = DEFAULT_HEIGHT_RATIO,
    bottom_margin_ratio: float = DEFAULT_BOTTOM_MARGIN_RATIO,
    max_width_ratio: float = DEFAULT_MAX_WIDTH_RATIO,
) -> bytes:
    if not scene_image:
        raise ValueError("场景图为空")
    if not product_png:
        raise ValueError("商品图为空")
    with Image.open(BytesIO(scene_image)) as scene_source:
        scene = ImageOps.exif_transpose(scene_source).convert("RGBA")
    with Image.open(BytesIO(product_png)) as product_source:
        product = product_source.convert("RGBA")

    left, top, target_width, target_height = product_box(
        scene.size, product.size, height_ratio=height_ratio,
        bottom_margin_ratio=bottom_margin_ratio, max_width_ratio=max_width_ratio,
    )
    product = product.resize((target_width, target_height), Image.LANCZOS)
    product = _match_lighting(scene, product)

    product = Image.open(BytesIO(add_contact_shadow(_to_png(product)))).convert("RGBA")
    canvas = scene.copy()
    canvas.alpha_composite(product, (left, top))
    return _to_png(canvas.convert("RGB"))


def product_box(
    scene_size: tuple[int, int],
    product_size: tuple[int, int],
    *,
    height_ratio: float = DEFAULT_HEIGHT_RATIO,
    bottom_margin_ratio: float = DEFAULT_BOTTOM_MARGIN_RATIO,
    max_width_ratio: float = DEFAULT_MAX_WIDTH_RATIO,
) -> tuple[int, int, int, int]:
    """商品在成图中的期望位置与尺寸：(left, top, width, height)。

    pixel_lock 与 keyframe_qa 共用同一套几何，保证"贴在哪"和"查哪"完全一致。
    高度与宽度双重约束：既不能让商品太小，也不能因等比放大而溢出画布。
    """
    scene_w, scene_h = scene_size
    product_w, product_h = product_size
    if product_w <= 0 or product_h <= 0 or scene_w <= 0 or scene_h <= 0:
        raise ValueError("商品或场景尺寸无效")
    height_ratio = max(0.1, min(0.95, height_ratio))
    scale = min((scene_h * height_ratio) / product_h, (scene_w * max_width_ratio) / product_w)
    width = max(1, int(product_w * scale))
    height = max(1, int(product_h * scale))
    left = max(0, (scene_w - width) // 2)
    top = max(0, int(scene_h * (1 - bottom_margin_ratio)) - height)
    return left, top, width, height


def _match_lighting(scene: Image.Image, product: Image.Image) -> Image.Image:
    bbox = product.getbbox()
    if bbox is None:
        return product
    region = scene.crop((0, 0, scene.width, scene.height)).convert("RGB")
    scene_stat = ImageStat.Stat(region)
    product_stat = ImageStat.Stat(product.convert("RGB"))
    diffs = []
    for scene_channel, product_channel in zip(scene_stat.mean, product_stat.mean):
        if product_channel <= 1:
            continue
        diffs.append(scene_channel / product_channel)
    if not diffs:
        return product
    factor = sum(diffs) / len(diffs)
    factor = max(MIN_LIGHT_FACTOR, min(MAX_LIGHT_FACTOR, factor))
    matched = ImageEnhance.Brightness(product.convert("RGB")).enhance(factor)
    return Image.merge("RGBA", (*matched.split(), product.split()[3]))


def _to_png(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()