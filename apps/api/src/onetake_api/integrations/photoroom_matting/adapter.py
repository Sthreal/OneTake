from __future__ import annotations

import httpx

from onetake_api.platform.errors import DomainError


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
        try:
            response = httpx.post(
                self._endpoint,
                headers={"x-api-key": self._api_key},
                files={"image_file": ("product.png", image_bytes, "image/png")},
                data={"format": "png"},
                timeout=120,
            )
            response.raise_for_status()
            return response.content
        except httpx.HTTPError as exc:
            raise PhotoroomMattingError("Photoroom 去背请求失败") from exc
