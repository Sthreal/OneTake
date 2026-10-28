"""用免 Key 素材填充空镜分段（批次 4a 的编排层）。

**只做一件事**：给定检索词与目标规格，返回一个可直接当分段视频用的 `StockFill`；拿不到就返回 `None`。
失败一律抛 `StockError`（由调用方回退到原 i2v 路径）——0 成本增强绝不能把成片搞失败。
"""
from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from onetake_api.integrations.stock import clip, registry
from onetake_api.integrations.stock.domain import StockAsset


@dataclass(frozen=True)
class StockFill:
    asset: StockAsset
    video_bytes: bytes
    head_frame_bytes: bytes
    tail_frame_bytes: bytes
    duration_seconds: float
    width: int
    height: int
    fps: int
    provider: str

    @property
    def attribution(self) -> str:
        return self.asset.attribution_line


def fill_from_stock(
    *,
    query: str,
    duration_seconds: float,
    width: int,
    height: int,
    fps: int,
    exclude_ids: Collection[str] = (),
    search_limit: int = 5,
    max_asset_bytes: int = clip.MAX_ASSET_BYTES,
    client=None,
) -> StockFill | None:
    """检索 → 下载 → 归一化 → 抽首尾帧。**检索不到返回 None；任何失败抛 StockError。**"""
    if not query.strip():
        return None
    asset = registry.find_video(query, limit=search_limit, exclude_ids=exclude_ids, client=client)
    if asset is None:
        return None
    source = clip.download_asset(asset, client=client, max_bytes=max_asset_bytes)
    normalized = clip.normalize_clip(
        source_bytes=source, duration_seconds=duration_seconds, width=width, height=height, fps=fps
    )
    head, tail = clip.head_and_tail_frames(normalized)
    return StockFill(
        asset=asset, video_bytes=normalized, head_frame_bytes=head, tail_frame_bytes=tail,
        duration_seconds=float(duration_seconds), width=width, height=height, fps=fps,
        provider=f"stock:{asset.source}",
    )