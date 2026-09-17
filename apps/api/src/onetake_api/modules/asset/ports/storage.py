from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class PresignedPut:
    url: str
    expires_at: datetime
    headers: dict[str, str]


@dataclass(frozen=True)
class ObjectInfo:
    size: int
    content_type: str | None
    etag: str | None


class AssetStoragePort(Protocol):
    def create_put_url(
        self,
        *,
        object_key: str,
        mime_type: str,
        expires_seconds: int,
    ) -> PresignedPut: ...

    def stat_object(self, *, object_key: str) -> ObjectInfo | None: ...

    def read_object(self, *, object_key: str) -> Iterator[bytes]: ...