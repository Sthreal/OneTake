from __future__ import annotations

import base64
from io import BytesIO

import httpx
from PIL import Image, UnidentifiedImageError

from onetake_api.platform.errors import DomainError

REQUEST_TIMEOUT_SECONDS = 120
MAX_RESULT_BYTES = 20 * 1024 * 1024
MAX_INPUT_IMAGES = 3
MAX_OUTPUT_IMAGES = 6
DEFAULT_EDIT_PROMPT = (
    "清理商品图片中的杂乱背景、外部文字、促销元素和无关物体，"
    "只保留完整商品主体；保持商品外观、包装文字、颜色和细节不变。"
)
DEFAULT_NEGATIVE_PROMPT = "水印, 促销文字, 标签卡, 多余物体, 商品变形, 改变颜色"


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

    def edit(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        prompt: str | None = None,
        negative_prompt: str | None = None,
    ) -> bytes:
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
                            {"text": prompt or DEFAULT_EDIT_PROMPT},
                        ],
                    }
                ]
            },
            "parameters": {
                "negative_prompt": negative_prompt or DEFAULT_NEGATIVE_PROMPT,
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

    def generate(
        self,
        *,
        images: list[tuple[bytes, str]],
        prompt: str,
        negative_prompt: str | None = None,
        n: int = 1,
        seed: int | None = None,
        size: str | None = None,
    ) -> list[bytes]:
        """多图融合生成（Phase 1 关键帧商品入画）。

        与 edit() 的区别：
        - 支持 1~3 张输入图（图1=商品主图，图2=场景/风格参考，图3=上一镜关键帧做一致性锚）
        - 支持 n 张候选输出（qwen-image-2.0 系列支持 1~6）
        - 支持 seed 复现与 prompt_extend
        """
        if not self._api_key:
            raise QwenImageEditError("DASHSCOPE_API_KEY 未配置")
        if not images:
            raise QwenImageEditError("多图生成缺少输入图")
        if len(images) > MAX_INPUT_IMAGES:
            raise QwenImageEditError(f"多图生成最多支持 {MAX_INPUT_IMAGES} 张输入图")
        if not prompt:
            raise QwenImageEditError("多图生成缺少提示词")
        content: list[dict] = []
        for image_bytes, mime_type in images:
            if not image_bytes:
                raise QwenImageEditError("多图生成存在空输入图")
            content.append({"image": f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"})
        content.append({"text": prompt})
        parameters: dict = {
            "negative_prompt": negative_prompt or DEFAULT_NEGATIVE_PROMPT,
            "watermark": False,
            "n": max(1, min(MAX_OUTPUT_IMAGES, int(n))),
        }
        if seed is not None:
            parameters["seed"] = int(seed)
        if size:
            # 关键帧必须是 9:16：多图输入时输出比例随最后一张图，显式指定更稳
            parameters["size"] = size
        payload = {
            "model": self._model,
            "input": {"messages": [{"role": "user", "content": content}]},
            "parameters": parameters,
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
        except httpx.HTTPStatusError as exc:
            # 带上供应商的错误码/原因：否则排查时只能看到"400"，得另写探针才能知道是欠费、限流还是参数问题
            detail = exc.response.text[:300].replace("\n", " ") if exc.response is not None else ""
            raise QwenImageEditError(f"Qwen Image Edit 多图生成请求失败：HTTP {exc.response.status_code} {detail}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise QwenImageEditError("Qwen Image Edit 多图生成请求失败") from exc
        urls = self._extract_image_urls(body)
        results: list[bytes] = []
        for image_url in urls:
            try:
                image_response = httpx.get(image_url, timeout=REQUEST_TIMEOUT_SECONDS)
                image_response.raise_for_status()
            except httpx.HTTPError as exc:
                raise QwenImageEditError("Qwen Image Edit 结果下载失败") from exc
            results.append(self._normalize_png(image_response.content))
        return results

    @staticmethod
    def _extract_image_urls(body: dict) -> list[str]:
        choices = body.get("output", {}).get("choices", [])
        urls: list[str] = []
        for choice in choices:
            content = choice.get("message", {}).get("content", [])
            if isinstance(content, str) and content.startswith("http"):
                urls.append(content)
                continue
            if not isinstance(content, list):
                continue
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("image"), str):
                    urls.append(item["image"])
        if not urls:
            raise QwenImageEditError("Qwen Image Edit 未返回图片")
        return urls

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
