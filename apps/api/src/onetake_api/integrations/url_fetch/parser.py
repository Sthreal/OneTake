"""商品页解析：OpenGraph → JSON-LD → 裸标签 三级回退（S13 提交 2）。

**纯函数、零 I/O**（只吃 HTML 字符串），因此可以用离线样本穷举测试。
只要有一级能给出"标题或图片"就算成功 —— 目标是"抓不全也能往下走"，不是"必须全中"。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin

MIN_FALLBACK_IMAGE_PX = 400


@dataclass(frozen=True)
class PageDraft:
    """从商品页抓到的东西。字段全部可为空 —— 抓不到就是空，由上层降级为手动上传。"""

    title: str | None = None
    price: str | None = None
    image_url: str | None = None
    source: str = "none"  # og | jsonld | fallback | none
    warnings: tuple[str, ...] = field(default_factory=tuple)


def _to_int(value: str | None) -> int | None:
    try:
        return int(str(value).strip().rstrip("px"))
    except (TypeError, ValueError):
        return None


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title_parts: list[str] = []
        self.images: list[tuple[str, int | None, int | None]] = []
        self.jsonld_blocks: list[str] = []
        self._in_title = False
        self._in_jsonld = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): (value or "") for key, value in attrs}
        if tag == "meta":
            key = (values.get("property") or values.get("name") or "").strip().lower()
            content = values.get("content", "").strip()
            if key and content:
                self.meta.setdefault(key, content)
        elif tag == "title":
            self._in_title = True
        elif tag == "script" and "ld+json" in values.get("type", "").lower():
            self._in_jsonld = True
        elif tag == "img":
            src = (values.get("src") or values.get("data-src") or "").strip()
            if src:
                self.images.append((src, _to_int(values.get("width")), _to_int(values.get("height"))))

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "script":
            self._in_jsonld = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data.strip())
        elif self._in_jsonld:
            self.jsonld_blocks.append(data)


def _walk_jsonld(node) -> dict | None:
    """在任意嵌套结构里找第一个像 Product 的字典。"""
    if isinstance(node, dict):
        types = node.get("@type")
        type_names = {types} if isinstance(types, str) else set(types or [])
        if "Product" in type_names:
            return node
        for value in node.values():
            found = _walk_jsonld(value)
            if found is not None:
                return found
        return None
    if isinstance(node, list):
        for item in node:
            found = _walk_jsonld(item)
            if found is not None:
                return found
    return None


def _first_str(value) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # JSON-LD 里的 price 常写成数字（`"price": 88` 而不是 `"88"`），按原样文本存
        return str(value)
    if isinstance(value, list) and value:
        return _first_str(value[0])
    if isinstance(value, dict):
        return _first_str(value.get("url") or value.get("contentUrl") or value.get("@id"))
    return None


def _from_jsonld(blocks: list[str]) -> tuple[str | None, str | None, str | None]:
    for block in blocks:
        try:
            data = json.loads(block)
        except (ValueError, TypeError):
            continue
        product = _walk_jsonld(data)
        if product is None:
            continue
        name = _first_str(product.get("name"))
        image = _first_str(product.get("image"))
        offers = product.get("offers")
        price = None
        if isinstance(offers, dict):
            price = _first_str(offers.get("price"))
        elif isinstance(offers, list) and offers:
            price = _first_str(offers[0].get("price")) if isinstance(offers[0], dict) else None
        if name or image:
            return name, price, image
    return None, None, None


def _pick_fallback_image(
    images: list[tuple[str, int | None, int | None]], warnings: list[str]
) -> str | None:
    if not images:
        return None
    big = [item for item in images if (item[1] or 0) >= MIN_FALLBACK_IMAGE_PX or (item[2] or 0) >= MIN_FALLBACK_IMAGE_PX]
    if big:
        return big[0][0]
    warnings.append("页面未声明图片尺寸，已取首张图片（可能不是主图）")
    return images[0][0]


def parse_product_page(html: str, *, base_url: str = "") -> PageDraft:
    """三级回退解析。返回的 `source` 说明最终用了哪一级（便于排障与统计）。"""
    extractor = _Extractor()
    extractor.feed(html or "")

    # 1) OpenGraph
    og_title = extractor.meta.get("og:title") or None
    og_image = extractor.meta.get("og:image") or None
    og_price = extractor.meta.get("product:price:amount") or extractor.meta.get("og:price:amount") or None
    if og_title or og_image:
        return PageDraft(
            title=og_title, price=og_price,
            image_url=urljoin(base_url, og_image) if og_image else None,
            source="og",
        )

    # 2) JSON-LD
    ld_title, ld_price, ld_image = _from_jsonld(extractor.jsonld_blocks)
    if ld_title or ld_image:
        return PageDraft(
            title=ld_title, price=ld_price,
            image_url=urljoin(base_url, ld_image) if ld_image else None,
            source="jsonld",
        )

    # 3) 裸标签
    warnings: list[str] = []
    title = " ".join(part for part in extractor.title_parts if part).strip() or None
    image = _pick_fallback_image(extractor.images, warnings)
    if title is None and image is None:
        warnings.append("页面里既没有标题也没有可用图片")
        return PageDraft(warnings=tuple(warnings))
    return PageDraft(
        title=title, price=None,
        image_url=urljoin(base_url, image) if image else None,
        source="fallback", warnings=tuple(warnings),
    )