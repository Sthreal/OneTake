"""Wikimedia Commons 客户端（免 Key，批次 4a 的"实拍视频兜底"+ 音频备选源）。

**实测口径**（2026-10-14 真调 `action=query&generator=search&gsrsearch=filetype:video ...`）：
`query.pages{}` → `imageinfo[0]` 含 `url / mime / width / height / duration`，
`extmetadata` 里 `LicenseShortName.value` 是许可、`Artist.value` 是作者（**含 HTML 标签，要剥**）。
"""
from __future__ import annotations

import html
import re
from typing import Any

import httpx

from onetake_api.integrations.stock.http import get_json
from onetake_api.integrations.stock.domain import (
    KIND_AUDIO,
    KIND_VIDEO,
    SOURCE_WIKIMEDIA,
    StockAsset,
    StockError,
    StockLicense,
)

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
FILE_NAMESPACE = "6"
_TAG_PATTERN = re.compile(r"<[^>]+>")


def search_videos(query: str, *, limit: int = 5, client: httpx.Client | None = None) -> list[StockAsset]:
    return _search(KIND_VIDEO, query, limit=limit, client=client)


def search_audio(query: str, *, limit: int = 5, client: httpx.Client | None = None) -> list[StockAsset]:
    return _search(KIND_AUDIO, query, limit=limit, client=client)


def _search(kind: str, query: str, *, limit: int, client: httpx.Client | None) -> list[StockAsset]:
    if not query.strip():
        raise StockError("素材检索词为空")
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"filetype:{kind} {query}",
        "gsrnamespace": FILE_NAMESPACE,
        "gsrlimit": str(max(1, min(limit, 20))),
        "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
    }
    try:
        # 统一走 http.get_json（UA / 超时 / 传输层重试）；Wikimedia 会对密集请求返回 403 robot policy
        body = get_json(url=COMMONS_API, params=params, client=client)
    except (httpx.HTTPError, ValueError) as exc:
        raise StockError(f"Wikimedia 检索失败：{query}") from exc
    pages = body.get("query", {}).get("pages") if isinstance(body, dict) else None
    if not isinstance(pages, dict):
        return []          # 无结果时 Wikimedia 直接不返回 query.pages（不是错误）
    assets: list[StockAsset] = []
    for page in pages.values():
        asset = _to_asset(kind, page)
        if asset is not None:
            assets.append(asset)
    return assets


def _to_asset(kind: str, page: Any) -> StockAsset | None:
    if not isinstance(page, dict):
        return None
    infos = page.get("imageinfo")
    if not isinstance(infos, list) or not infos:
        return None
    info = infos[0]
    if not isinstance(info, dict):
        return None
    mime = str(info.get("mime") or "")
    if not mime.startswith(f"{kind}/"):
        return None                                            # 防串味：只要对应媒体的文件
    download_url = str(info.get("url") or "").split("?")[0]     # Wikimedia 会挂 utm 参数，剥掉
    if not download_url:
        return None
    meta = info.get("extmetadata") if isinstance(info.get("extmetadata"), dict) else {}
    title = str(page.get("title") or "").removeprefix("File:")
    return StockAsset(
        asset_id=str(page.get("pageid") or download_url),
        kind=kind,
        source=SOURCE_WIKIMEDIA,
        provider="wikimedia-commons",
        title=title or "untitled",
        download_url=download_url,
        landing_url=f"https://commons.wikimedia.org/wiki/File:{title.replace(' ', '_')}" if title else None,
        creator=_text(meta.get("Artist")) or _text(meta.get("Credit")),
        license=StockLicense(
            name=_text(meta.get("LicenseShortName")) or "Unknown",
            url=_text(meta.get("LicenseUrl")),
        ),
        width=_int_or_none(info.get("width")),
        height=_int_or_none(info.get("height")),
        duration_seconds=_float_or_none(info.get("duration")),
    )


def _text(node: Any) -> str | None:
    """extmetadata 的值形如 `{"value": "<a href=...>Author</a>"}` → 剥标签、去空白。"""
    if not isinstance(node, dict):
        return None
    raw = node.get("value")
    if raw is None:
        return None
    plain = html.unescape(_TAG_PATTERN.sub("", str(raw))).strip()
    return plain or None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None