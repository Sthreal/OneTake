from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageChops, ImageFilter, ImageStat

from onetake_api.platform.errors import DomainError


class MockMattingError(DomainError):
    code = "MATTING_PROVIDER_ERROR"
    http_status = 502
    retryable = True


class MockMattingAdapter:
    provider_name = "mock-photoroom"

    def remove_background(self, *, image_bytes: bytes) -> bytes:
        try:
            with Image.open(BytesIO(image_bytes)) as source:
                image = source.convert("RGBA")
        except (OSError, ValueError) as exc:
            raise MockMattingError("Mock 去背无法读取源图片") from exc

        width, height = image.size
        if width < 2 or height < 2:
            raise MockMattingError("Mock 去背图片尺寸无效")

        rgb = image.convert("RGB")
        edge = Image.new("RGB", (width * 2 + height * 2, 1))
        edge.paste(rgb.crop((0, 0, width, 1)), (0, 0))
        edge.paste(rgb.crop((0, height - 1, width, height)), (width, 0))
        edge.paste(rgb.crop((0, 0, 1, height)), (width * 2, 0))
        edge.paste(rgb.crop((width - 1, 0, width, height)), (width * 2 + height, 0))
        background = tuple(int(value) for value in ImageStat.Stat(edge).mean[:3])
        difference = ImageChops.difference(rgb, Image.new("RGB", image.size, background)).convert("L")
        mask = difference.point(lambda value: 255 if value > 24 else 0)
        mask = mask.filter(ImageFilter.GaussianBlur(1.1))
        if mask.getbbox() is not None:
            alpha = ImageChops.multiply(image.getchannel("A"), mask)
            image.putalpha(alpha)

        output = BytesIO()
        image.save(output, format="PNG", optimize=True)
        return output.getvalue()


