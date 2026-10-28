"""Openverse 客户端（免 Key，批次 4a 的"优先源"）。

**实测口径**（2026-10-14 真调 `GET https://api.openverse.org/v1/images?q=...`）：
返回 `{"results": [...]}`，每条含 `id / title / url / creator / license / license_version /
license_url / width / height / foreign_landing_url / provider`。

⚠️ 事实核对：Openverse **只有图片与音频，没有视频**（`/v1/images`、`/v1/audio`）。
所以视频空镜的兜底走 `wikimedia.py`；Openverse 在本仓的用途是**图片**与**音频（BGM 音源）**。
"""
from __future__ import annotations

from typing import Any

import httpx

from onetake_api.integrations.stock.http import get_json
from onetake_api.integrations.stock.domain import (
    KIND_AUDIO,
    KIND_IMAGE,
    SOURCE_OPENVERSE,
    StockAsset,
    StockError,
    StockLicense,
)

OPENVERSE_BASE = "https://api.openverse.org/v1"


def search_images(query: str, *, limit: int = 5, client: httpx.Client | None = None) -> list[StockAsset]:
    return _search(KIND_IMAGE, query, limit=limit, client=client)


def search_audio(query: str, *, limit: int = 5, client: httpx.Client | None = None) -> list[StockAsset]:
    return _search(KIND_AUDIO, query, limit=limit, client=client)


def _search(kind: str, query: str, *, limit: int, client: httpx.Client | None) -> list[StockAsset]:
    if not query.strip():
        raise StockError("素材检索词为空")
    try:
        # 统一走 http.get_json：UA / 超时 / 跟随重定向（Openverse 301 到带尾斜杠形式）/ 传输层重试
        body = get_json(
            url=f"{OPENVERSE_BASE}/{kind}s/",
            params={"q": query, "page_size": max(1, min(limit, 20)), "license_type": "all"},
            client=client,
        )
    except (httpx.HTTPError, ValueError) as exc:
        raise StockError(f"Openverse 检索失败：{query}") from exc
    results = body.get("results") if isinstance(body, dict) else None
    if not isinstance(results, list):
        raise StockError("Openverse 返回结构不符合预期")
    assets: list[StockAsset] = []
    for item in results:
        asset = _to_asset(kind, item)
        if asset is not None:
            assets.append(asset)
    return assets


def _to_asset(kind: str, item: Any) -> StockAsset | None:
    if not isinstance(item, dict):
        return None
    download_url = str(item.get("url") or "").strip()
    if not download_url:
        return None
    return StockAsset(
        asset_id=str(item.get("id") or download_url),
        kind=kind,
        source=SOURCE_OPENVERSE,
        provider=str(item.get("provider") or SOURCE_OPENVERSE),
        title=str(item.get("title") or "untitled"),
        download_url=download_url,
        landing_url=(str(item["foreign_landing_url"]) if item.get("foreign_landing_url") else None),
        creator=(str(item["creator"]) if item.get("creator") else None),
        license=StockLicense(
            name=license_name(item.get("license"), item.get("license_version")),
            url=(str(item["license_url"]) if item.get("license_url") else None),
        ),
        width=_int_or_none(item.get("width")),
        height=_int_or_none(item.get("height")),
        # Openverse 音频/视频的 duration 单位是**毫秒**
        duration_seconds=_ms_to_seconds(item.get("duration")),
    )


def license_name(value: Any, version: Any) -> str:
    """`by` + `2.0` → `CC BY 2.0`；`cc0` → `CC0`；`pdm` → `Public domain`。"""
    raw = (str(value) if value else "").strip().lower()
    if not raw:
        return "Unknown"
    if raw in {"cc0", "cc-zero"}:
        return "CC0"
    if raw in {"pdm", "publicdomain"}:
        return "Public domain"
    suffix = f" {version}" if version else ""
    return f"CC {raw.upper()}{suffix}"


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _ms_to_seconds(value: Any) -> float | None:
    milliseconds = _int_or_none(value)
    return None if milliseconds is None else round(milliseconds / 1000, 3)