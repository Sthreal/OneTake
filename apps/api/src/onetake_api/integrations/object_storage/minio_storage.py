from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

from minio import Minio
from minio.error import S3Error

from onetake_api.modules.asset.ports.storage import ObjectInfo, PresignedPut


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