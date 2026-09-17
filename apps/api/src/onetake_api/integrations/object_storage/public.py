from __future__ import annotations

from collections.abc import Iterator

from onetake_api.modules.asset.ports.storage import (
    AssetStoragePort,
    ObjectInfo,
    PresignedGet,
    PresignedPut,
)


class ObjectStoragePublicService:
    def __init__(self, storage: AssetStoragePort) -> None:
        self._storage = storage

    def create_put_url(
        self,
        *,
        object_key: str,
        mime_type: str,
        expires_seconds: int,
    ) -> PresignedPut:
        return self._storage.create_put_url(
            object_key=object_key,
            mime_type=mime_type,
            expires_seconds=expires_seconds,
        )

    def create_get_url(self, *, object_key: str, expires_seconds: int) -> PresignedGet:
        return self._storage.create_get_url(
            object_key=object_key,
            expires_seconds=expires_seconds,
        )

    def stat_object(self, *, object_key: str) -> ObjectInfo | None:
        return self._storage.stat_object(object_key=object_key)

    def read_object(self, *, object_key: str) -> Iterator[bytes]:
        return self._storage.read_object(object_key=object_key)

    def put_bytes(
        self,
        *,
        object_key: str,
        content: bytes,
        mime_type: str,
    ) -> ObjectInfo:
        return self._storage.put_bytes(
            object_key=object_key,
            content=content,
            mime_type=mime_type,
        )
