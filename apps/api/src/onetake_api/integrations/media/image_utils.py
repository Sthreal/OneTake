from __future__ import annotations

from io import BytesIO
from math import ceil

from PIL import Image, ImageDraw, ImageFilter, ImageOps

VERTICAL_9_16_RATIO = 9 / 16
VERTICAL_9_16_SIZE_MULTIPLE = 256
RATIO_TOLERANCE = 0.01


def pad_image_to_9_16(image_bytes: bytes) -> bytes:
    if not image_bytes:
        raise ValueError("输入图片为空")
    with Image.open(BytesIO(image_bytes)) as source:
        image = ImageOps.exif_transpose(source).convert("RGBA")
        width, height = image.size
        if width <= 0 or height <= 0:
            raise ValueError("输入图片尺寸无效")
        if abs(width / height - VERTICAL_9_16_RATIO) <= RATIO_TOLERANCE:
            canvas = Image.new("RGB", (width, height), (255, 255, 255))
            canvas.paste(image, (0, 0), image)
            output = BytesIO()
            canvas.save(output, format="PNG")
            return output.getvalue()

        target_height = ceil(max(height, width / VERTICAL_9_16_RATIO) / VERTICAL_9_16_SIZE_MULTIPLE) * VERTICAL_9_16_SIZE_MULTIPLE
        target_width = int(target_height * VERTICAL_9_16_RATIO)
        canvas = Image.new("RGB", (target_width, target_height), (255, 255, 255))
        offset = ((target_width - width) // 2, (target_height - height) // 2)
        canvas.paste(image, offset, image)
        output = BytesIO()
        canvas.save(output, format="PNG")
        return output.getvalue()


def add_contact_shadow(image_bytes: bytes, *, blur_radius: int = 18, opacity: int = 90) -> bytes:
    if not image_bytes:
        raise ValueError("输入图片为空")
    with Image.open(BytesIO(image_bytes)) as source:
        image = source.convert("RGBA")
        bbox = image.getbbox()
        if bbox is None:
            return image_bytes
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(shadow)
        draw.ellipse(
            (
                bbox[0] + width * 0.12,
                bbox[3] - height * 0.08,
                bbox[2] - width * 0.12,
                bbox[3] + height * 0.1,
            ),
            fill=(0, 0, 0, max(0, min(255, opacity))),
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(max(0, blur_radius)))
        shadow.alpha_composite(image)
        output = BytesIO()
        shadow.save(output, format="PNG", optimize=True)
        return output.getvalue()
