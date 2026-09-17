from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image

from onetake_api.platform.errors import DomainError

PNG_SIZE = 2000
JPG_SIZE = 1000
PRODUCT_TARGET_RATIO = 0.82
MAX_JPG_BYTES = 3 * 1024 * 1024


class MainImageProcessingError(DomainError):
    code = "MAIN_IMAGE_PROCESSING_ERROR"
    http_status = 500
    retryable = True


@dataclass(frozen=True)
class StandardizedMainImage:
    png_bytes: bytes
    jpg_bytes: bytes
    png_width: int
    png_height: int
    jpg_width: int
    jpg_height: int
    jpg_size_bytes: int
    product_ratio: float


def _prepare_product(content: bytes) -> Image.Image:
    try:
        with Image.open(BytesIO(content)) as source:
            image = source.convert("RGBA")
    except (OSError, ValueError) as exc:
        raise MainImageProcessingError("无法读取去背结果") from exc

    alpha = image.getchannel("A")
    bounds = alpha.getbbox()
    if bounds is None:
        opaque = Image.new("RGBA", image.size, (0, 0, 0, 0))
        opaque.paste(image.convert("RGB"), (0, 0))
        image = opaque
        bounds = image.getbbox()
    if bounds is None:
        raise MainImageProcessingError("去背结果没有可见商品")

    product = image.crop(bounds)
    max_product_side = int(PNG_SIZE * PRODUCT_TARGET_RATIO)
    scale = min(max_product_side / product.width, max_product_side / product.height)
    target_size = (
        max(1, round(product.width * scale)),
        max(1, round(product.height * scale)),
    )
    return product.resize(target_size, Image.Resampling.LANCZOS)


def _encode_png(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _encode_jpg(image: Image.Image) -> bytes:
    for quality in (92, 88, 84, 80, 76, 72):
        output = BytesIO()
        image.convert("RGB").save(output, format="JPEG", quality=quality, optimize=True, progressive=True)
        content = output.getvalue()
        if len(content) <= MAX_JPG_BYTES:
            return content
    raise MainImageProcessingError("白底 JPG 压缩后仍超过 3 MB")


def standardize_main_image(content: bytes) -> StandardizedMainImage:
    product = _prepare_product(content)
    canvas = Image.new("RGBA", (PNG_SIZE, PNG_SIZE), (0, 0, 0, 0))
    offset = ((PNG_SIZE - product.width) // 2, (PNG_SIZE - product.height) // 2)
    canvas.alpha_composite(product, dest=offset)
    png_bytes = _encode_png(canvas)

    white = Image.new("RGBA", (JPG_SIZE, JPG_SIZE), (255, 255, 255, 255))
    product_for_jpg = product.resize(
        (
            max(1, round(product.width * JPG_SIZE / PNG_SIZE)),
            max(1, round(product.height * JPG_SIZE / PNG_SIZE)),
        ),
        Image.Resampling.LANCZOS,
    )
    white.alpha_composite(
        product_for_jpg,
        dest=((JPG_SIZE - product_for_jpg.width) // 2, (JPG_SIZE - product_for_jpg.height) // 2),
    )
    jpg_bytes = _encode_jpg(white)
    ratio = max(product.width, product.height) / PNG_SIZE
    return StandardizedMainImage(
        png_bytes=png_bytes,
        jpg_bytes=jpg_bytes,
        png_width=canvas.width,
        png_height=canvas.height,
        jpg_width=JPG_SIZE,
        jpg_height=JPG_SIZE,
        jpg_size_bytes=len(jpg_bytes),
        product_ratio=round(ratio, 4),
    )
