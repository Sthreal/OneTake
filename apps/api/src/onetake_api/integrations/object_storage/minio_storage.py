from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from io import BytesIO

from minio import Minio
from minio.error import S3Error

from onetake_api.modules.asset.ports.storage import ObjectInfo, PresignedGet, PresignedPut


class MinioAssetStorage:
    def __init__(
        self,
        *,
        internal_client: Minio,
        public_client: Minio,
        bucket: str,
    ) -> None:
        self._internal_client = internal_client
        self._public_client = public_client
        self._bucket = bucket

    def create_put_url(
        self,
        *,
        object_key: str,
        mime_type: str,
        expires_seconds: int,
    ) -> PresignedPut:
        url = self._public_client.presigned_put_object(
            self._bucket,
            object_key,
            expires=timedelta(seconds=expires_seconds),
        )
        return PresignedPut(
            url=url,
            expires_at=datetime.now(UTC) + timedelta(seconds=expires_seconds),
            headers={"Content-Type": mime_type},
        )

    def create_get_url(self, *, object_key: str, expires_seconds: int) -> PresignedGet:
        url = self._public_client.presigned_get_object(
            self._bucket,
            object_key,
            expires=timedelta(seconds=expires_seconds),
        )
        return PresignedGet(
            url=url,
            expires_at=datetime.now(UTC) + timedelta(seconds=expires_seconds),
        )

    def stat_object(self, *, object_key: str) -> ObjectInfo | None:
        try:
            result = self._internal_client.stat_object(self._bucket, object_key)
            return ObjectInfo(
                size=result.size,
                content_type=result.content_type,
                etag=result.etag,
            )
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
                return None
            raise

    def read_object(self, *, object_key: str) -> Iterator[bytes]:
        response = self._internal_client.get_object(self._bucket, object_key)
        try:
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            response.close()
            response.release_conn()

    def delete_object(self, *, object_key: str) -> None:
        try:
            self._internal_client.remove_object(self._bucket, object_key)
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
                return
            raise

    def list_objects(self, *, prefix: str) -> list[str]:
        return [item.object_name for item in self._internal_client.list_objects(self._bucket, prefix=prefix, recursive=True)]

    def delete_prefix(self, *, prefix: str) -> int:
        object_keys = self.list_objects(prefix=prefix)
        for object_key in object_keys:
            self.delete_object(object_key=object_key)
        return len(object_keys)

    def put_bytes(self, *, object_key: str, content: bytes, mime_type: str) -> ObjectInfo:
        stream = BytesIO(content)
        result = self._internal_client.put_object(
            self._bucket,
            object_key,
            stream,
            length=len(content),
            content_type=mime_type,
        )
        return ObjectInfo(size=len(content), content_type=mime_type, etag=result.etag)
