from __future__ import annotations

import base64
import json
from io import BytesIO

import httpx
from PIL import Image, UnidentifiedImageError

from onetake_api.modules.script.domain import ScriptDraft, ScriptInput
from onetake_api.platform.errors import DomainError

REQUEST_TIMEOUT_SECONDS = 120
MAX_PROVIDER_SIDE = 1600


class QwenVlScriptError(DomainError):
    code = "SCRIPT_PROVIDER_ERROR"
    http_status = 502
    retryable = True


class QwenVlScriptAdapter:
    provider_name = "qwen-vl-plus"

    def __init__(self, *, api_key: str, endpoint: str, model: str) -> None:
        self._api_key = api_key
        self._endpoint = endpoint
        self.model = model

    def generate(self, *, image_bytes: bytes, mime_type: str, script_input: ScriptInput) -> ScriptDraft:
        if not self._api_key:
            raise QwenVlScriptError("DASHSCOPE_API_KEY 未配置")
        if not image_bytes:
            raise QwenVlScriptError("文案输入主图为空")
        image_url = self._data_url(image_bytes)
        facts = {
            "商品名称": script_input.product_name,
            "商品补充说明": script_input.product_note or "",
            "痛点": script_input.pain_point,
            "已确认卖点": list(script_input.selling_points),
            "使用场景": script_input.usage_scenario,
            "优惠信息": script_input.offer or "",
        }
        prompt = (
            "请根据图片和以下已确认事实生成约 20 秒的强带货中文口播文案。"
            "只能使用提供的事实，不得添加销量、价格、折扣、认证、功效或其他未提供数字。"
            "文案应自然、口语化，包含钩子、痛点、卖点、使用场景和 CTA。"
            "全文去除标点后必须为 85–120 个中文字符，建议控制在 100 字左右。"
            "selling_points 必须与已确认卖点逐条对应，数量必须与输入一致，不得增加未提供的卖点。"
            "不得添加未提供的品牌、成分、功效、价格或数量。"
            "输出严格 JSON，字段只能是 hook、pain_point、selling_points、usage_scenario、cta；"
            "selling_points 必须是字符串数组。不要输出 Markdown。事实："
            + json.dumps(facts, ensure_ascii=False)
        )
        try:
            response = httpx.post(
                self._endpoint,
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                json={"model": self.model, "input": {"messages": [{"role": "user", "content": [{"image": image_url}, {"text": prompt}]}]}},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise QwenVlScriptError("Qwen-VL-Plus 文案请求失败") from exc

        text = self._extract_text(body)
        try:
            parsed = json.loads(self._extract_json(text))
            if not isinstance(parsed, dict):
                raise ValueError("response must be an object")
            points = parsed["selling_points"]
            if not isinstance(points, list) or not all(isinstance(point, str) for point in points):
                raise ValueError("selling_points is invalid")
            return ScriptDraft(
                hook=str(parsed["hook"]),
                pain_point=str(parsed["pain_point"]),
                selling_points=script_input.selling_points,
                usage_scenario=str(parsed["usage_scenario"]),
                cta=str(parsed["cta"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise QwenVlScriptError("Qwen-VL-Plus 返回的文案结构无效") from exc

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
                rgb.save(output, format="JPEG", quality=88, optimize=True)
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise QwenVlScriptError("文案输入主图无法发送") from exc
        encoded = base64.b64encode(output.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"

    @staticmethod
    def _extract_text(body: dict) -> str:
        choices = body.get("output", {}).get("choices", [])
        if not choices:
            raise QwenVlScriptError("Qwen-VL-Plus 未返回文案")
        content = choices[0].get("message", {}).get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(item.get("text", "") for item in content if isinstance(item, dict))
        raise QwenVlScriptError("Qwen-VL-Plus 返回内容格式无效")

    @staticmethod
    def _extract_json(text: str) -> str:
        normalized = text.strip()
        fence = chr(96) * 3
        if normalized.startswith(fence):
            lines = normalized.splitlines()
            if lines and lines[0].startswith(fence):
                lines = lines[1:]
            if lines and lines[-1].strip() == fence:
                lines = lines[:-1]
            normalized = " ".join(lines).strip()
            if normalized.lower().startswith("json"):
                normalized = normalized[4:].strip()
        start = normalized.find("{")
        end = normalized.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise QwenVlScriptError("Qwen-VL-Plus 未返回 JSON")
        return normalized[start : end + 1]
