from __future__ import annotations

from io import BytesIO
from math import ceil

from PIL import Image, ImageOps

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
