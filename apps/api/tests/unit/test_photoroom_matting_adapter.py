from io import BytesIO

import pytest
from PIL import Image

from onetake_api.integrations.photoroom_matting.adapter import PhotoroomMattingAdapter, PhotoroomMattingError


def _rgba_png() -> bytes:
    output = BytesIO()
    Image.new("RGBA", (200, 200), (30, 120, 220, 255)).save(output, format="PNG")
    return output.getvalue()


def _rgb_jpeg() -> bytes:
    output = BytesIO()
    Image.new("RGB", (200, 200), (30, 120, 220)).save(output, format="JPEG")
    return output.getvalue()


class FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


def test_photoroom_returns_normalized_transparent_png(monkeypatch) -> None:
    monkeypatch.setattr(
        "onetake_api.integrations.photoroom_matting.adapter.httpx.post",
        lambda *args, **kwargs: FakeResponse(_rgba_png()),
    )
    adapter = PhotoroomMattingAdapter(api_key="test-key", endpoint="https://example.test/segment")
    result = adapter.remove_background(image_bytes=_rgba_png())
    with Image.open(BytesIO(result)) as image:
        assert image.format == "PNG"
        assert image.mode == "RGBA"
        assert image.getchannel("A").getbbox() is not None


def test_photoroom_rejects_opaque_jpeg(monkeypatch) -> None:
    monkeypatch.setattr(
        "onetake_api.integrations.photoroom_matting.adapter.httpx.post",
        lambda *args, **kwargs: FakeResponse(_rgb_jpeg()),
    )
    adapter = PhotoroomMattingAdapter(api_key="test-key", endpoint="https://example.test/segment")
    with pytest.raises(PhotoroomMattingError):
        adapter.remove_background(image_bytes=_rgba_png())
