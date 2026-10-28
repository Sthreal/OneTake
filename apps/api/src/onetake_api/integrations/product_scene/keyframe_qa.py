"""关键帧质检（Phase 1）：判断商品是否真的"入画"且未被改坏。

两条实现：
- RuleKeyframeQaAdapter：离线/确定性。检查①商品区域是否被占据（不是纯背景）②商品区域与参考图的
  色板/亮度是否接近③商品区域边缘能量（文字可辨的代理指标）。零成本，可在 MOCK_PROVIDERS 下跑通。
- QwenVlKeyframeQaAdapter：真实 VLM 判定商品一致性、包装文字是否变形、有无多余主体或乱码文字。

两者输出同一结构，供 keyframe_generation 决定是否走 pixel-lock 兜底。
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from io import BytesIO
from typing import Protocol

import httpx
from PIL import Image, ImageFilter, ImageOps, ImageStat

from onetake_api.integrations.product_scene.pixel_lock import product_box

REQUEST_TIMEOUT_SECONDS = 120
# 判定阈值（可解释、不外显为"分数"）：色板相似度、区域占据率、边缘能量
MIN_PRODUCT_MATCH = 0.55
MIN_REGION_VARIANCE = 12.0
MIN_TEXT_EDGE_RATIO = 0.002


@dataclass(frozen=True)
class KeyframeQaResult:
    passed: bool
    product_present: bool
    product_match: float
    text_intact: bool
    issues: list[str] = field(default_factory=list)
    provider: str = "rules"
    model: str = "rules-v1"


class KeyframeQaPort(Protocol):
    provider_name: str
    model_name: str

    def evaluate(self, *, image_bytes: bytes, product_png: bytes) -> KeyframeQaResult:
        ...


def _open(image_bytes: bytes) -> Image.Image:
    with Image.open(BytesIO(image_bytes)) as source:
        return ImageOps.exif_transpose(source).convert("RGB")


def _product_region(image: Image.Image, product: Image.Image) -> tuple[int, int, int, int]:
    """商品应当出现的位置：与 pixel_lock 共用同一套几何，避免"贴"与"查"错位。"""
    left, top, width, height = product_box(image.size, product.size)
    return (left, top, min(image.width, left + width), min(image.height, top + height))


def _visible_pixels(image: Image.Image) -> Image.Image:
    """裁掉透明边距，只留商品可见区域。"""
    bbox = image.getbbox()
    return image.crop(bbox) if bbox else image


def _color_similarity(product: Image.Image, region: Image.Image) -> float:
    """逐通道均值距离（归一化到 0~1 的相似度）。

    用颜色而不是亮度：商品往往是高饱和色块，亮度均值会把"红色商品 vs 米色背景"
    误判成接近。距离上界为 sqrt(3*255^2)。
    """
    product_stat = ImageStat.Stat(_visible_pixels(product.convert("RGB")))
    region_stat = ImageStat.Stat(region.convert("RGB"))
    squared = sum((a - b) ** 2 for a, b in zip(product_stat.mean, region_stat.mean))
    distance = (squared ** 0.5) / ((3 * 255 * 255) ** 0.5)
    return max(0.0, min(1.0, 1.0 - distance))


def _edge_ratio(region: Image.Image, threshold: int = 20) -> float:
    """边缘像素占比：作为"细节是否糊掉"的代理指标（纯背景接近 0）。"""
    edges = region.convert("L").filter(ImageFilter.FIND_EDGES).point(lambda value: 255 if value >= threshold else 0)
    histogram = edges.histogram()
    total = max(1, region.width * region.height)
    return histogram[255] / total


class RuleKeyframeQaAdapter:
    """离线确定性质检：能在 MOCK_PROVIDERS 下跑通，不产生任何付费调用。"""

    provider_name = "rules"
    model_name = "rules-v1"

    def evaluate(self, *, image_bytes: bytes, product_png: bytes) -> KeyframeQaResult:
        issues: list[str] = []
        image = _open(image_bytes)
        product = _open(product_png)

        if image.height <= image.width or abs(image.width / image.height - 9 / 16) > 0.02:
            issues.append("画面不是 9:16 竖版")

        region_box = _product_region(image, product)
        region = image.crop(region_box)
        variance = sum(ImageStat.Stat(region).stddev) / 3
        product_present = variance >= MIN_REGION_VARIANCE
        if not product_present:
            issues.append("商品位置是空背景，商品未入画")

        product_match = _color_similarity(product, region)
        if product_match < MIN_PRODUCT_MATCH:
            issues.append("商品区域与主图颜色差异过大")

        text_intact = _edge_ratio(region) >= MIN_TEXT_EDGE_RATIO
        if not text_intact:
            issues.append("商品区域细节不足，包装文字可能模糊")

        passed = product_present and product_match >= MIN_PRODUCT_MATCH
        return KeyframeQaResult(
            passed=passed, product_present=product_present, product_match=round(product_match, 3),
            text_intact=text_intact, issues=issues,
        )


class QwenVlKeyframeQaAdapter:
    """真实 VLM 质检（qwen-vl 系列）：判定保真与文字，返回结构化结论。"""

    provider_name = "qwen-vl-keyframe"
    model_name = "qwen-vl-plus"

    def __init__(self, *, api_key: str, endpoint: str, model: str) -> None:
        self._api_key = api_key
        self._endpoint = endpoint
        self.model_name = model

    def evaluate(self, *, image_bytes: bytes, product_png: bytes) -> KeyframeQaResult:
        if not self._api_key:
            raise KeyframeQaError("DASHSCOPE_API_KEY 未配置")
        images = [
            {"image": _data_url(image_bytes)},
            {"image": _data_url(product_png)},
        ]
        payload = {
            "model": self.model_name,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            *images,
                            {"text": _PROMPT},
                        ],
                    }
                ]
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
            raise KeyframeQaError("关键帧质检请求失败") from exc
        content = body.get("output", {}).get("choices", [{}])[0].get("message", {}).get("content")
        if isinstance(content, list):
            content = "".join(item.get("text", "") for item in content if isinstance(item, dict))
        return _parse(str(content or ""))


class KeyframeQaError(Exception):
    pass


_PROMPT = (
    "第一张是关键帧成图，第二张是商品主图（透明底）。请判断："
    "1) 成图里是否出现该商品；2) 商品外观/配色/结构是否与主图一致；"
    "3) 包装上的文字与 LOGO 是否清晰、可辨认、未被变形；"
    "4) 是否存在多余商品、多余主体或乱码文字。"
    "只输出 JSON：{\"product_present\":bool,\"product_match\":0-1,\"text_intact\":bool,\"issues\":[string]}"
)


def _parse(text: str) -> KeyframeQaResult:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise KeyframeQaError("关键帧质检返回内容无法解析")
    try:
        data = json.loads(cleaned[start : end + 1])
    except ValueError as exc:
        raise KeyframeQaError("关键帧质检返回内容不是 JSON") from exc
    issues = [str(item) for item in data.get("issues", []) if str(item).strip()]
    product_present = bool(data.get("product_present"))
    try:
        product_match = float(data.get("product_match", 0.0))
    except (TypeError, ValueError):
        product_match = 0.0
    text_intact = bool(data.get("text_intact"))
    if not product_present:
        issues.append("商品未入画")
    return KeyframeQaResult(
        passed=product_present and product_match >= MIN_PRODUCT_MATCH, product_present=product_present,
        product_match=round(product_match, 3), text_intact=text_intact, issues=issues,
        provider=QwenVlKeyframeQaAdapter.provider_name,
    )


def _data_url(image_bytes: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")


def get_keyframe_qa(settings) -> KeyframeQaPort:
    """按配置选择质检实现；真实 VLM 缺 Key 时明确报错，不静默降级。"""
    provider = getattr(settings, "keyframe_qa_provider", "rules")
    if provider == "qwen":
        if not settings.dashscope_api_key:
            raise KeyframeQaError("关键帧质检缺少 DASHSCOPE_API_KEY")
        return QwenVlKeyframeQaAdapter(
            api_key=settings.dashscope_api_key,
            endpoint=settings.content_qa_endpoint,
            model=getattr(settings, "keyframe_qa_model", settings.content_qa_model),
        )
    return RuleKeyframeQaAdapter()