from __future__ import annotations

import json

import httpx

from onetake_api.modules.content_plan.domain import ContentVariant
from onetake_api.platform.errors import DomainError


class QwenCreativeError(DomainError):
    code = "CONTENT_PLAN_PROVIDER_ERROR"
    http_status = 502
    retryable = True


class QwenCreativePlanner:
    provider_name = "qwen-plus"

    def __init__(self, *, api_key: str, endpoint: str, model: str, client: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._endpoint = endpoint
        self.model = model
        self._client = client or httpx.Client(timeout=120)

    def enhance(self, *, variants: list[ContentVariant], facts: dict) -> list[ContentVariant]:
        if not self._api_key:
            raise QwenCreativeError("DASHSCOPE_API_KEY 未配置")
        source = {
            "variants": [
                {"variant_id": variant.variant_id, "style": variant.style, "scenes": [{"scene_id": scene.scene_id, "purpose": scene.purpose, "script_excerpt": scene.script_excerpt} for scene in variant.scenes]}
                for variant in variants
            ]
        }
        prompt = (
            "你是电商短视频视觉导演。只优化镜头、背景和光线，不得修改文案、时间轴、商品事实、价格、销量、认证或功效。"
            "严格输出 JSON，格式为 {\"variants\":[{\"variant_id\":\"...\",\"scenes\":[{\"scene_id\":\"...\",\"prompt\":\"...\",\"shot_type\":\"...\",\"background_style\":\"...\"}]}]}。"
            "每个输入 scene_id 必须且只能出现一次，不得增加 scene_id。事实和分镜骨架："
            + json.dumps({"facts": facts, "source": source}, ensure_ascii=False)
        )
        try:
            response = self._client.post(
                self._endpoint,
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                json={"model": self.model, "input": {"messages": [{"role": "user", "content": prompt}]}, "parameters": {"result_format": "message"}},
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise QwenCreativeError("Qwen-Plus 分镜创意请求失败") from exc
        try:
            content = body["output"]["choices"][0]["message"]["content"]
            parsed = json.loads(self._extract_json(content))
            updates = {}
            for variant in parsed["variants"]:
                for scene in variant["scenes"]:
                    updates[(str(variant["variant_id"]), str(scene["scene_id"]))] = scene
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise QwenCreativeError("Qwen-Plus 分镜结构无效") from exc
        result = []
        for variant in variants:
            scenes = []
            for scene in variant.scenes:
                update = updates.get((variant.variant_id, scene.scene_id))
                if update is None:
                    raise QwenCreativeError("Qwen-Plus 缺少分镜场景")
                prompt_text = str(update.get("prompt", "")).strip()
                shot_type = str(update.get("shot_type", "")).strip()
                background = str(update.get("background_style", "")).strip()
                if not prompt_text or not shot_type or not background:
                    raise QwenCreativeError("Qwen-Plus 分镜字段为空")
                scenes.append(type(scene)(**{**scene.__dict__, "prompt": prompt_text, "shot_type": shot_type, "background_style": background}))
            result.append(type(variant)(variant.variant_id, variant.name, variant.style, scenes))
        return result

    @staticmethod
    def _extract_json(text: str) -> str:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise QwenCreativeError("Qwen-Plus 未返回 JSON")
        return text[start : end + 1]
