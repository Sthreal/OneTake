from hashlib import sha256
from io import BytesIO

from minio import Minio
from PIL import Image

from onetake_api.integrations.object_storage.public import ObjectStoragePublicService


def _png_bytes(width: int = 600, height: int = 600) -> bytes:
    stream = BytesIO()
    Image.new("RGB", (width, height), (240, 90, 30)).save(stream, format="PNG")
    return stream.getvalue()


def test_minio_asset_storage_round_trip(
    minio_client: Minio,
    object_storage: ObjectStoragePublicService,
) -> None:
    content = _png_bytes()
    object_key = f"tests/assets/{sha256(content).hexdigest()}.png"
    minio_client.put_object(
        "onetake-media",
        object_key,
        BytesIO(content),
        length=len(content),
        content_type="image/png",
    )

    info = object_storage.stat_object(object_key=object_key)
    assert info is not None
    assert info.size == len(content)
    assert b"".join(object_storage.read_object(object_key=object_key)) == content