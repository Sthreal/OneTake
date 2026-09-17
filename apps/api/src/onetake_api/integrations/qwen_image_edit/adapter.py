from __future__ import annotations

import base64

import httpx

from onetake_api.platform.errors import DomainError


class QwenImageEditError(DomainError):
    code = "IMAGE_EDIT_PROVIDER_ERROR"
    http_status = 502
    retryable = True


class QwenImageEditAdapter:
    provider_name = "qwen-image-edit-plus"

    def __init__(self, *, api_key: str, endpoint: str, model: str) -> None:
        self._api_key = api_key
        self._endpoint = endpoint
        self._model = model

    def edit(self, *, image_bytes: bytes, mime_type: str) -> bytes:
        if not self._api_key:
            raise QwenImageEditError("DASHSCOPE_API_KEY 未配置")
        data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
        payload = {
            "model": self._model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"image": data_url},
                            {"text": "清理商品图片中的杂乱背景、文字和促销元素，只保留完整商品主体，不改变商品外观。"},
                        ],
                    }
                ]
            },
            "parameters": {"negative_prompt": "水印, 文字, 标签, 品牌 Logo, 多余物体", "watermark": False},
        }
        try:
            response = httpx.post(
                self._endpoint,
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=120,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise QwenImageEditError("Qwen Image Edit 请求失败") from exc

        image_url = self._extract_image_url(body)
        try:
            image_response = httpx.get(image_url, timeout=120)
            image_response.raise_for_status()
            return image_response.content
        except httpx.HTTPError as exc:
            raise QwenImageEditError("Qwen Image Edit 结果下载失败") from exc

    @staticmethod
    def _extract_image_url(body: dict) -> str:
        choices = body.get("output", {}).get("choices", [])
        for choice in choices:
            content = choice.get("message", {}).get("content", [])
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("image"), str):
                    return item["image"]
        raise QwenImageEditError("Qwen Image Edit 未返回图片")
