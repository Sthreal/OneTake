from __future__ import annotations

from io import BytesIO

import httpx
from PIL import Image, UnidentifiedImageError

from onetake_api.platform.errors import DomainError

REQUEST_TIMEOUT_SECONDS = 120
MAX_RESULT_BYTES = 20 * 1024 * 1024


class PhotoroomMattingError(DomainError):
    code = "MATTING_PROVIDER_ERROR"
    http_status = 502
    retryable = True


class PhotoroomMattingAdapter:
    provider_name = "photoroom"

    def __init__(self, *, api_key: str, endpoint: str) -> None:
        self._api_key = api_key
        self._endpoint = endpoint

    def remove_background(self, *, image_bytes: bytes) -> bytes:
        if not self._api_key:
            raise PhotoroomMattingError("PHOTOROOM_API_KEY 未配置")
        if not image_bytes:
            raise PhotoroomMattingError("去背输入为空")
        try:
            response = httpx.post(
                self._endpoint,
                headers={"x-api-key": self._api_key},
                files={"image_file": ("product.png", image_bytes, "image/png")},
                data={"format": "png"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PhotoroomMattingError("Photoroom 去背请求失败") from exc
        return self._normalize_transparent_png(response.content)

    @staticmethod
    def _normalize_transparent_png(content: bytes) -> bytes:
        if not content:
            raise PhotoroomMattingError("Photoroom 返回空文件")
        if len(content) > MAX_RESULT_BYTES:
            raise PhotoroomMattingError("Photoroom 返回文件超过 20 MB")
        try:
            with Image.open(BytesIO(content)) as source:
                if (source.format or "").upper() != "PNG" or "A" not in source.getbands():
                    raise PhotoroomMattingError("Photoroom 未返回透明 PNG")
                image = source.convert("RGBA")
                if image.getchannel("A").getbbox() is None:
                    raise PhotoroomMattingError("Photoroom 返回图片没有可见主体")
                output = BytesIO()
                image.save(output, format="PNG", optimize=True)
                return output.getvalue()
        except PhotoroomMattingError:
            raise
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise PhotoroomMattingError("Photoroom 返回内容不是有效 PNG") from exc
