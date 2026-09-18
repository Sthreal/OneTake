from io import BytesIO

import pytest
from PIL import Image

from onetake_api.integrations.qwen_image_edit.adapter import QwenImageEditAdapter, QwenImageEditError


def _png(color=(30, 120, 220, 255)) -> bytes:
    output = BytesIO()
    Image.new("RGBA", (200, 200), color).save(output, format="PNG")
    return output.getvalue()


class FakeResponse:
    def __init__(self, *, content: bytes = b"", body: dict | None = None) -> None:
        self.content = content
        self._body = body or {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._body


def test_qwen_image_edit_downloads_and_normalizes_png(monkeypatch) -> None:
    monkeypatch.setattr(
        "onetake_api.integrations.qwen_image_edit.adapter.httpx.post",
        lambda *args, **kwargs: FakeResponse(body={"output": {"choices": [{"message": {"content": [{"image": "https://example.test/edited"}]}}]}}),
    )
    monkeypatch.setattr(
        "onetake_api.integrations.qwen_image_edit.adapter.httpx.get",
        lambda *args, **kwargs: FakeResponse(content=_png()),
    )
    adapter = QwenImageEditAdapter(api_key="test-key", endpoint="https://example.test/edit", model="qwen-image-edit-plus")
    result = adapter.edit(image_bytes=_png(), mime_type="image/png")
    with Image.open(BytesIO(result)) as image:
        assert image.format == "PNG"
        assert image.mode == "RGB"


def test_qwen_image_edit_rejects_non_image_result(monkeypatch) -> None:
    monkeypatch.setattr(
        "onetake_api.integrations.qwen_image_edit.adapter.httpx.post",
        lambda *args, **kwargs: FakeResponse(body={"output": {"choices": [{"message": {"content": [{"image": "https://example.test/error"}]}}]}}),
    )
    monkeypatch.setattr(
        "onetake_api.integrations.qwen_image_edit.adapter.httpx.get",
        lambda *args, **kwargs: FakeResponse(content=b"<html>bad gateway</html>"),
    )
    adapter = QwenImageEditAdapter(api_key="test-key", endpoint="https://example.test/edit", model="qwen-image-edit-plus")
    with pytest.raises(QwenImageEditError):
        adapter.edit(image_bytes=_png(), mime_type="image/png")
