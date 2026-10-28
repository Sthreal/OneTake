from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from io import BytesIO

import httpx
from PIL import Image, UnidentifiedImageError

from onetake_api.modules.script.copy_rules import COPY_RULE_PROMPT
from onetake_api.modules.script.domain import ScriptDraft, ScriptInput
from onetake_api.platform.errors import DomainError

REVIEW_DIMENSIONS: tuple[str, ...] = ("rhythm", "spoken", "freshness", "structure")


@dataclass(frozen=True)
class ScriptReview:
    """审稿结果：4 维度判定 + 改写后的整稿 + **由前后比对得出**的改动清单。"""

    dimensions: dict[str, dict]
    revised: "ScriptDraft"
    changed_fields: list[str]
    provider: str
    model: str

    @property
    def failed_dimensions(self) -> list[str]:
        return [name for name, item in self.dimensions.items() if not item.get("passed")]


def _facts_payload(script_input: ScriptInput) -> dict:
    return {
        "商品名称": script_input.product_name,
        "商品补充说明": script_input.product_note or "",
        "痛点": script_input.pain_point,
        "已确认卖点": list(script_input.selling_points),
        "使用场景": script_input.usage_scenario,
        "优惠信息": script_input.offer or "",
    }


def _diff_fields(before: "ScriptDraft", after: "ScriptDraft") -> list[str]:
    changed: list[str] = []
    for field in ("hook", "pain_point", "usage_scenario", "cta"):
        if getattr(before, field) != getattr(after, field):
            changed.append(field)
    if list(before.selling_points) != list(after.selling_points):
        changed.append("selling_points")
    return changed

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

    def generate(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        script_input: ScriptInput,
        angle: str | None = None,
    ) -> ScriptDraft:
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
            "全文去除标点后必须为 45–72 个中文字符，建议控制在 60 字左右（短版，保证配音 ≤15 秒）。"
            "selling_points 必须与已确认卖点逐条对应，数量必须与输入一致，不得增加未提供的卖点。"
            "不得添加未提供的品牌、成分、功效、价格或数量。"
            f"{COPY_RULE_PROMPT}"
            "输出严格 JSON，字段只能是 hook、pain_point、selling_points、usage_scenario、cta；"
            "selling_points 必须是字符串数组。不要输出 Markdown。事实："
            + json.dumps(facts, ensure_ascii=False)
        )
        if angle is not None:
            from onetake_api.modules.script.angles import angle_prompt_suffix

            try:
                prompt += angle_prompt_suffix(angle)
            except ValueError as exc:
                raise QwenVlScriptError(str(exc)) from exc
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

    # ---- 批次 2b：审稿（4 维度 + 只重写不合格的单句）----

    def review(self, *, script_input: ScriptInput, draft: ScriptDraft) -> ScriptReview:
        """对已成稿的文案做一次**审稿**：4 维度判定 + 只重写不合格的单句。

        - **纯文本调用**（不重复发图）：审的是文案本身，图片信息已在事实里；
        - 约束与生成阶段**逐条一致**（只用已确认事实、不得新增数字/价格/品牌、卖点条数必须一致、45-72 字）；
        - `changed_fields` 由**前后文本比对**得出，而不是听模型自称 —— 模型说改了但文本没变的，不算改动。
        """
        if not self._api_key:
            raise QwenVlScriptError("DASHSCOPE_API_KEY 未配置")
        facts = _facts_payload(script_input)
        current = {
            "hook": draft.hook, "pain_point": draft.pain_point,
            "selling_points": list(draft.selling_points),
            "usage_scenario": draft.usage_scenario, "cta": draft.cta,
        }
        prompt = (
            "你是中文口播文案审稿人。请审下面这份带货文案，按 4 个维度判定（每维给 passed 与一句理由）："
            "rhythm（节奏：句子长短与停顿是否适合口播）、spoken（口语化：是否像人说的话）、"
            "freshness（新鲜度：是否避免陈词滥调）、structure（结构完整性：钩子/痛点/卖点/场景/CTA 是否齐备）。"
            f"{COPY_RULE_PROMPT}"
            "若 hook 命中套话开场，freshness.passed 必须为 false；"
            "若前 3 秒钩子停不住拇指，或缺少 usage_scenario 末尾轻提 / cta 行动号召，structure.passed 必须为 false。"
            "**只重写不合格的那几句**，合格的句子必须原样保留；不得新增事实、数字、价格、折扣、认证、功效或品牌；"
            f"selling_points 的条数必须与输入一致（{len(draft.selling_points)} 条）；"
            "改写后全文去掉标点仍须为 45-72 个中文字符（短版口径，与生成阶段一致）。"
            "输出严格 JSON："
            '{"dimensions":{"rhythm":{"passed":true,"reason":"…"},"spoken":{...},"freshness":{...},"structure":{...}},'
            '"revised":{"hook":"…","pain_point":"…","selling_points":["…"],"usage_scenario":"…","cta":"…"}}。'
            "不要输出 Markdown。已确认事实："
            + json.dumps(facts, ensure_ascii=False)
            + "当前文案：" + json.dumps(current, ensure_ascii=False)
        )
        try:
            response = httpx.post(
                self._endpoint,
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                json={"model": self.model, "input": {"messages": [{"role": "user", "content": [{"text": prompt}]}]}},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise QwenVlScriptError("Qwen-VL-Plus 审稿请求失败") from exc

        text = self._extract_text(body)
        try:
            parsed = json.loads(self._extract_json(text))
            if not isinstance(parsed, dict):
                raise ValueError("response must be an object")
            dimensions = parsed["dimensions"]
            if not isinstance(dimensions, dict) or any(name not in dimensions for name in REVIEW_DIMENSIONS):
                raise ValueError("dimensions invalid")
            revised = parsed["revised"]
            points = revised["selling_points"]
            if not isinstance(points, list) or not all(isinstance(point, str) for point in points):
                raise ValueError("selling_points invalid")
            if len(points) != len(draft.selling_points):
                raise ValueError("selling_points 条数被改动")
            if any(not str(point).strip() for point in points):
                raise ValueError("selling_points 出现空句")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise QwenVlScriptError("Qwen-VL-Plus 返回的审稿结构无效") from exc

        candidate = ScriptDraft(
            hook=str(revised["hook"]), pain_point=str(revised["pain_point"]),
            selling_points=[str(point) for point in points],
            usage_scenario=str(revised["usage_scenario"]), cta=str(revised["cta"]),
        )
        return ScriptReview(
            dimensions={
                name: {
                    "passed": bool(dict(dimensions[name]).get("passed")),
                    "reason": str(dict(dimensions[name]).get("reason", "")),
                }
                for name in REVIEW_DIMENSIONS
            },
            revised=candidate,
            changed_fields=_diff_fields(draft, candidate),
            provider=QwenVlScriptAdapter.provider_name,
            model=self.model,
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
