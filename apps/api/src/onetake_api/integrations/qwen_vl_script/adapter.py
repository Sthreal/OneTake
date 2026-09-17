from __future__ import annotations

import base64
import json
import re

import httpx

from onetake_api.modules.script.domain import ScriptDraft, ScriptInput
from onetake_api.platform.errors import DomainError

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


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

    def generate(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        script_input: ScriptInput,
    ) -> ScriptDraft:
        if not self._api_key:
            raise QwenVlScriptError("DASHSCOPE_API_KEY 未配置")
        image_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
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
            "输出严格 JSON，字段为 hook、pain_point、selling_points、usage_scenario、cta；"
            "selling_points 必须是字符串数组。\n事实："
            + json.dumps(facts, ensure_ascii=False)
        )
        try:
            response = httpx.post(
                self._endpoint,
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "input": {
                        "messages": [
                            {
                                "role": "user",
                                "content": [{"image": image_url}, {"text": prompt}],
                            }
                        ]
                    },
                },
                timeout=120,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise QwenVlScriptError("Qwen-VL-Plus 文案请求失败") from exc

        text = self._extract_text(body)
        try:
            parsed = json.loads(self._extract_json(text))
            points = parsed["selling_points"]
            if not isinstance(points, list) or not all(isinstance(point, str) for point in points):
                raise ValueError("selling_points is invalid")
            return ScriptDraft(
                hook=str(parsed["hook"]),
                pain_point=str(parsed["pain_point"]),
                selling_points=tuple(points),
                usage_scenario=str(parsed["usage_scenario"]),
                cta=str(parsed["cta"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise QwenVlScriptError("Qwen-VL-Plus 返回的文案结构无效") from exc

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
        match = _JSON_BLOCK_RE.search(text)
        if match:
            return match.group(1)
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise QwenVlScriptError("Qwen-VL-Plus 未返回 JSON")
        return text[start : end + 1]
