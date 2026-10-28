"""免费素材（stock）的领域对象与错误（批次 4a）。

**为什么要有 `attribution`**：免 Key 的免费素材多带 CC 署名要求 —— 用了就得留痕，
否则用户拿去做商业投放会踩授权。所以"来源 + 许可 + 作者"是**一等字段**，不是日志。
"""
from __future__ import annotations

from dataclasses import dataclass

from onetake_api.platform.errors import DomainError

KIND_IMAGE = "image"
KIND_VIDEO = "video"
KIND_AUDIO = "audio"
SOURCE_OPENVERSE = "openverse"
SOURCE_WIKIMEDIA = "wikimedia"

# 这些许可**不要求署名**（仍会记录来源，便于追溯）
NO_ATTRIBUTION_MARKERS = ("cc0", "public domain", "pdm")


class StockError(DomainError):
    """素材检索/下载失败。**由调用方决定是否降级**（0 成本路径的原则：素材拿不到就回退原路径）。"""

    code = "STOCK_SEARCH_ERROR"
    http_status = 502
    retryable = True


@dataclass(frozen=True)
class StockLicense:
    name: str
    url: str | None = None

    @property
    def requires_attribution(self) -> bool:
        lowered = self.name.lower()
        return not any(marker in lowered for marker in NO_ATTRIBUTION_MARKERS)


@dataclass(frozen=True)
class StockAsset:
    asset_id: str
    kind: str
    source: str
    provider: str
    title: str
    download_url: str
    license: StockLicense
    landing_url: str | None = None
    creator: str | None = None
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None

    @property
    def attribution_line(self) -> str:
        """一行可粘贴的署名（CC 要求"作者 + 许可 + 链接"，这里三样都给）。"""
        parts = [f'"{self.title}"']
        if self.creator:
            parts.append(f"by {self.creator}")
        parts.append(f"({self.license.name})")
        link = self.landing_url or self.download_url
        parts.append(f"— {link}")
        return " ".join(parts)

    @property
    def requires_attribution(self) -> bool:
        return self.license.requires_attribution