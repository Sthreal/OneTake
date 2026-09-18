from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

from onetake_api.integrations.aliyun_imageseg.adapter import AliyunCommodityMattingAdapter, AliyunCommodityMattingError


def _product_png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (300, 240), (30, 120, 220)).save(output, format="PNG")
    return output.getvalue()


def _mask_png(*, size=(300, 240), color=255) -> bytes:
    output = BytesIO()
    Image.new("L", size, color).save(output, format="PNG")
    return output.getvalue()


class FakeMaskResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


def _adapter() -> AliyunCommodityMattingAdapter:
    return AliyunCommodityMattingAdapter(
        access_key_id="test-id",
        access_key_secret="test-secret",
        region_id="cn-shanghai",
        endpoint="imageseg.cn-shanghai.aliyuncs.com",
    )


def test_aliyun_segment_commodity_composes_transparent_png(monkeypatch) -> None:
    adapter = _adapter()
    monkeypatch.setattr(
        adapter,
        "_segment",
        lambda image_bytes: SimpleNamespace(body=SimpleNamespace(data=SimpleNamespace(image_url="https://example.test/mask.png"))),
    )
    monkeypatch.setattr(
        "onetake_api.integrations.aliyun_imageseg.adapter.httpx.get",
        lambda *args, **kwargs: FakeMaskResponse(_mask_png(size=(150, 120))),
    )
    result = adapter.remove_background(image_bytes=_product_png())
    with Image.open(BytesIO(result)) as image:
        assert image.format == "PNG"
        assert image.mode == "RGBA"
        assert image.size == (300, 240)
        assert image.getchannel("A").getbbox() is not None


def test_aliyun_requires_access_key() -> None:
    adapter = AliyunCommodityMattingAdapter(
        access_key_id="",
        access_key_secret="",
        region_id="cn-shanghai",
        endpoint="imageseg.cn-shanghai.aliyuncs.com",
    )
    with pytest.raises(AliyunCommodityMattingError):
        adapter.remove_background(image_bytes=_product_png())


def test_aliyun_rejects_empty_mask(monkeypatch) -> None:
    adapter = _adapter()
    monkeypatch.setattr(
        adapter,
        "_segment",
        lambda image_bytes: SimpleNamespace(body=SimpleNamespace(data=SimpleNamespace(image_url="https://example.test/mask.png"))),
    )
    monkeypatch.setattr(
        "onetake_api.integrations.aliyun_imageseg.adapter.httpx.get",
        lambda *args, **kwargs: FakeMaskResponse(_mask_png(color=0)),
    )
    with pytest.raises(AliyunCommodityMattingError):
        adapter.remove_background(image_bytes=_product_png())
