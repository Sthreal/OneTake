from __future__ import annotations

import base64
from io import BytesIO

import httpx
from PIL import Image, UnidentifiedImageError

from onetake_api.platform.errors import DomainError

REQUEST_TIMEOUT_SECONDS = 120
MAX_RESULT_BYTES = 20 * 1024 * 1024


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
        if not image_bytes:
            raise QwenImageEditError("图像编辑输入为空")
        data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
        payload = {
            "model": self._model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"image": data_url},
                            {
                                "text": (
                                    "清理商品图片中的杂乱背景、外部文字、促销元素和无关物体，"
                                    "只保留完整商品主体；保持商品外观、包装文字、颜色和细节不变。"
                                )
                            },
                        ],
                    }
                ]
            },
            "parameters": {
                "negative_prompt": "水印, 促销文字, 标签卡, 多余物体, 商品变形, 改变颜色",
                "watermark": False,
            },
        }
        try:
            response = httpx.post(
                self._endpoint,
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise QwenImageEditError("Qwen Image Edit 请求失败") from exc

        image_url = self._extract_image_url(body)
        try:
            image_response = httpx.get(image_url, timeout=REQUEST_TIMEOUT_SECONDS)
            image_response.raise_for_status()
        except httpx.HTTPError as exc:
            raise QwenImageEditError("Qwen Image Edit 结果下载失败") from exc
        return self._normalize_png(image_response.content)

    @staticmethod
    def _extract_image_url(body: dict) -> str:
        choices = body.get("output", {}).get("choices", [])
        for choice in choices:
            content = choice.get("message", {}).get("content", [])
            if isinstance(content, str) and content.startswith("http"):
                return content
            if not isinstance(content, list):
                continue
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("image"), str):
                    return item["image"]
        raise QwenImageEditError("Qwen Image Edit 未返回图片")

    @staticmethod
    def _normalize_png(content: bytes) -> bytes:
        if not content:
            raise QwenImageEditError("Qwen Image Edit 返回空文件")
        if len(content) > MAX_RESULT_BYTES:
            raise QwenImageEditError("Qwen Image Edit 返回文件超过 20 MB")
        try:
            with Image.open(BytesIO(content)) as source:
                image = source.convert("RGB")
                output = BytesIO()
                image.save(output, format="PNG", optimize=True)
                return output.getvalue()
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise QwenImageEditError("Qwen Image Edit 返回内容不是有效图片") from exc
