from __future__ import annotations

import base64
import json
import re
from io import BytesIO

import httpx
from PIL import Image

from onetake_api.modules.recognition.domain import CandidateDraft
from onetake_api.modules.recognition.port import RecognitionImage
from onetake_api.platform.errors import DomainError

MAX_PROVIDER_SIDE = 1600
MAX_CANDIDATES = 5
MIN_CONFIDENCE = 0.5
_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\[.*\]|\{.*\})\s*```", re.DOTALL)


class QwenRecognitionError(DomainError):
    code = "RECOGNITION_PROVIDER_ERROR"
    http_status = 502
    retryable = True


class QwenRecognitionAdapter:
    provider_name = "qwen-vl-plus"
    requires_images = True

    def __init__(self, *, api_key: str, endpoint: str, model: str) -> None:
        self._api_key = api_key
        self._endpoint = endpoint
        self._model = model

    def recognize(
        self,
        *,
        project_name: str,
        product_note: str | None,
        images: list[RecognitionImage],
    ) -> list[CandidateDraft]:
        if not self._api_key:
            raise QwenRecognitionError("DASHSCOPE_API_KEY 未配置")
        if not images:
            raise QwenRecognitionError("没有可识别的素材")

        asset_ids = {image.asset_id for image in images}
        content: list[dict[str, str]] = [{"text": self._prompt(project_name, product_note, images)}]
        for image in images:
            if image.content is None:
                raise QwenRecognitionError("真实识别缺少素材内容")
            content.append({"image": self._data_url(image.content)})

        try:
            response = httpx.post(
                self._endpoint,
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                json={
                    "model": self._model,
                    "input": {"messages": [{"role": "user", "content": content}]},
                },
                timeout=120,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise QwenRecognitionError("Qwen-VL-Plus 识别请求失败") from exc

        parsed = self._parse_json(self._extract_text(body))
        candidates = parsed.get("candidates") if isinstance(parsed, dict) else parsed
        if not isinstance(candidates, list) or not candidates:
            raise QwenRecognitionError("Qwen-VL-Plus 未返回有效候选")

        drafts: list[CandidateDraft] = []
        seen: set[str] = set()
        for item in candidates:
            if not isinstance(item, dict):
                continue
            asset_id = str(item.get("asset_id", ""))
            if asset_id not in asset_ids or asset_id in seen:
                continue
            try:
                confidence = float(item.get("confidence", 0))
            except (TypeError, ValueError):
                continue
            if confidence < MIN_CONFIDENCE:
                continue
            label = str(item.get("label", "")).strip()[:120]
            reason = str(item.get("reason", "")).strip()[:240]
            if not label or not reason:
                continue
            drafts.append(
                CandidateDraft(
                    asset_id=asset_id,
                    label=label,
                    confidence=min(1.0, max(0.0, confidence)),
                    reason=reason,
                )
            )
            seen.add(asset_id)
            if len(drafts) >= MAX_CANDIDATES:
                break
        if not drafts:
            raise QwenRecognitionError("Qwen-VL-Plus 候选未通过校验")
        return drafts

    @staticmethod
    def _prompt(project_name: str, product_note: str | None, images: list[RecognitionImage]) -> str:
        candidates = [
            {"asset_id": image.asset_id, "filename": image.original_filename}
            for image in images
        ]
        return (
            "你是电商商品识别助手。请结合商品名称、补充说明和图片，只判断图片中是否包含目标商品。"
            "只允许返回给定 asset_id，禁止编造。按可能性从高到低返回 1–5 个候选。"
            "严格输出 JSON：{\"candidates\":[{\"asset_id\":\"...\",\"label\":\"...\","
            "\"confidence\":0.0,\"reason\":\"...\"}]}。"
            f"商品名称：{project_name}；补充说明：{product_note or '无'}；素材："
            + json.dumps(candidates, ensure_ascii=False)
        )

    @staticmethod
    def _data_url(content: bytes) -> str:
        try:
            with Image.open(BytesIO(content)) as source:
                image = source.convert("RGBA")
                background = Image.new("RGBA", image.size, (255, 255, 255, 255))
                background.alpha_composite(image)
                rgb = background.convert("RGB")
                rgb.thumbnail((MAX_PROVIDER_SIDE, MAX_PROVIDER_SIDE), Image.Resampling.LANCZOS)
                output = BytesIO()
                rgb.save(output, format="JPEG", quality=85, optimize=True)
        except (OSError, ValueError) as exc:
            raise QwenRecognitionError("素材图片无法发送给识别 Provider") from exc
        encoded = base64.b64encode(output.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"

    @staticmethod
    def _extract_text(body: dict) -> str:
        choices = body.get("output", {}).get("choices", [])
        if not choices:
            raise QwenRecognitionError("Qwen-VL-Plus 未返回识别结果")
        content = choices[0].get("message", {}).get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(item.get("text", "") for item in content if isinstance(item, dict))
        raise QwenRecognitionError("Qwen-VL-Plus 返回内容格式无效")

    @staticmethod
    def _parse_json(text: str):
        match = _JSON_BLOCK_RE.search(text)
        raw = match.group(1) if match else text
        if not match:
            start_array = raw.find("[")
            start_object = raw.find("{")
            starts = [value for value in (start_array, start_object) if value >= 0]
            if not starts:
                raise QwenRecognitionError("Qwen-VL-Plus 未返回 JSON")
            start = min(starts)
            end = max(raw.rfind("]"), raw.rfind("}"))
            if end <= start:
                raise QwenRecognitionError("Qwen-VL-Plus 返回 JSON 不完整")
            raw = raw[start : end + 1]
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise QwenRecognitionError("Qwen-VL-Plus 返回 JSON 无效") from exc
