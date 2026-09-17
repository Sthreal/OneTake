import pytest

from onetake_api.modules.asset.domain.errors import AssetValidationError
from onetake_api.modules.asset.domain.model import (
    normalize_mime_type,
    normalize_sha256,
    validate_image_metadata,
)


def test_valid_image_metadata() -> None:
    validate_image_metadata(
        mime_type="image/png",
        size_bytes=1024,
        width=800,
        height=600,
    )


def test_mime_type_is_normalized() -> None:
    assert normalize_mime_type(" IMAGE/PNG ") == "image/png"


@pytest.mark.parametrize(
    ("mime_type", "size_bytes", "width", "height"),
    [
        ("image/gif", 1024, 800, 600),
        ("image/png", 10 * 1024 * 1024 + 1, 800, 600),
        ("image/png", 1024, 100, 600),
        ("image/png", 1024, 5000, 500),
    ],
)
def test_invalid_metadata_is_rejected(
    mime_type: str,
    size_bytes: int,
    width: int,
    height: int,
) -> None:
    with pytest.raises(AssetValidationError):
        validate_image_metadata(
            mime_type=mime_type,
            size_bytes=size_bytes,
            width=width,
            height=height,
        )


def test_sha256_is_normalized() -> None:
    assert normalize_sha256("A" * 64) == "a" * 64


def test_invalid_sha256_is_rejected() -> None:
    with pytest.raises(AssetValidationError):
        normalize_sha256("abc")