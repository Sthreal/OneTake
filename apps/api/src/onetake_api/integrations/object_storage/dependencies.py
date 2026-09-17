from functools import lru_cache

from minio import Minio

from onetake_api.config import get_settings
from onetake_api.integrations.object_storage.minio_storage import MinioAssetStorage
from onetake_api.integrations.object_storage.public import ObjectStoragePublicService


def _build_client(endpoint: str) -> Minio:
    settings = get_settings()
    return Minio(
        endpoint,
        access_key=settings.minio_root_user,
        secret_key=settings.minio_root_password,
        secure=settings.minio_secure,
        region=settings.minio_region,
    )


@lru_cache
def get_object_storage() -> ObjectStoragePublicService:
    settings = get_settings()
    storage = MinioAssetStorage(
        internal_client=_build_client(settings.minio_endpoint),
        public_client=_build_client(settings.minio_public_endpoint),
        bucket=settings.minio_bucket,
    )
    return ObjectStoragePublicService(storage)