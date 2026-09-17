from __future__ import annotations

from io import BytesIO

from PIL import Image

from onetake_api.platform.errors import DomainError


class MockImageEditError(DomainError):
    code = "IMAGE_EDIT_PROVIDER_ERROR"
    http_status = 502
    retryable = True


class MockImageEditAdapter:
    provider_name = "mock-qwen-image-edit-plus"

    def edit(self, *, image_bytes: bytes, mime_type: str) -> bytes:
        try:
            with Image.open(BytesIO(image_bytes)) as image:
                normalized = image.convert("RGBA")
                output = BytesIO()
                normalized.save(output, format="PNG", optimize=True)
                return output.getvalue()
        except (OSError, ValueError) as exc:
            raise MockImageEditError("Mock 图像编辑无法读取源图片") from exc
