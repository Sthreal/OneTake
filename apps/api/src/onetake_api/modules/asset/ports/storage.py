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
class PresignedGet:
    url: str
    expires_at: datetime


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

    def create_get_url(
        self,
        *,
        object_key: str,
        expires_seconds: int,
    ) -> PresignedGet: ...

    def stat_object(self, *, object_key: str) -> ObjectInfo | None: ...

    def read_object(self, *, object_key: str) -> Iterator[bytes]: ...

    def delete_object(self, *, object_key: str) -> None: ...

    def list_objects(self, *, prefix: str) -> list[str]: ...

    def delete_prefix(self, *, prefix: str) -> int: ...

    def put_bytes(
        self,
        *,
        object_key: str,
        content: bytes,
        mime_type: str,
    ) -> ObjectInfo: ...
