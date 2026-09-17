from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from onetake_api.modules.asset.domain.errors import AssetValidationError

ASSET_STATUS_PENDING = "pending"
ASSET_STATUS_READY = "ready"
ASSET_STATUS_FAILED = "failed"

ALLOWED_MIME_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
PIL_FORMAT_TO_MIME = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}
MAX_ASSETS_PER_PROJECT = 5
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024
MIN_SHORT_SIDE = 512
MAX_LONG_SIDE = 6000
MAX_PIXELS = 24_000_000
MAX_ASPECT_RATIO = 5.0
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class Asset:
    id: str
    project_id: str
    object_key: str
    original_filename: str
    mime_type: str
    size_bytes: int
    width: int
    height: int
    sha256: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


def normalize_sha256(value: str) -> str:
    normalized = value.strip().lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise AssetValidationError("sha256 必须是 64 位十六进制字符串")
    return normalized


def normalize_mime_type(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in ALLOWED_MIME_TYPES:
        raise AssetValidationError("仅支持 JPG、PNG 和 WebP")
    return normalized


def extension_for_mime_type(mime_type: str) -> str:
    return ALLOWED_MIME_TYPES[normalize_mime_type(mime_type)]


def validate_image_metadata(
    *,
    mime_type: str,
    size_bytes: int,
    width: int,
    height: int,
) -> None:
    if size_bytes <= 0:
        raise AssetValidationError("图片大小必须大于 0")
    if size_bytes > MAX_FILE_SIZE_BYTES:
        raise AssetValidationError("单张图片不能超过 10 MB")
    if width <= 0 or height <= 0:
        raise AssetValidationError("图片尺寸无效")
    short_side = min(width, height)
    long_side = max(width, height)
    if short_side < MIN_SHORT_SIDE:
        raise AssetValidationError("图片短边不能小于 512 px")
    if long_side > MAX_LONG_SIDE:
        raise AssetValidationError("图片长边不能超过 6000 px")
    if width * height > MAX_PIXELS:
        raise AssetValidationError("图片总像素不能超过 24 MP")
    if long_side / short_side > MAX_ASPECT_RATIO:
        raise AssetValidationError("图片比例必须在 1:5 到 5:1 之间")
    normalize_mime_type(mime_type)


def create_pending_asset(
    *,
    asset_id: str,
    project_id: str,
    object_key: str,
    original_filename: str,
    mime_type: str,
    size_bytes: int,
    width: int,
    height: int,
    sha256: str | None,
    now: datetime,
) -> Asset:
    normalized_mime = normalize_mime_type(mime_type)
    validate_image_metadata(
        mime_type=normalized_mime,
        size_bytes=size_bytes,
        width=width,
        height=height,
    )
    normalized_sha = normalize_sha256(sha256) if sha256 else None
    return Asset(
        id=asset_id,
        project_id=project_id,
        object_key=object_key,
        original_filename=original_filename.strip(),
        mime_type=normalized_mime,
        size_bytes=size_bytes,
        width=width,
        height=height,
        sha256=normalized_sha,
        status=ASSET_STATUS_PENDING,
        created_at=now,
        updated_at=now,
        completed_at=None,
    )