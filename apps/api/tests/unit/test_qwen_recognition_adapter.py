from io import BytesIO

import pytest
from PIL import Image

from onetake_api.integrations.qwen_recognition.adapter import QwenRecognitionAdapter, QwenRecognitionError
from onetake_api.modules.recognition.port import RecognitionImage


def _png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (900, 900), (245, 245, 245)).save(output, format="PNG")
    return output.getvalue()


class FakeResponse:
    def __init__(self, body: dict) -> None:
        self._body = body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._body


def test_qwen_recognition_validates_candidate_ids(monkeypatch) -> None:
    captured = {}

    def fake_post(url, *, headers, json, timeout):
        captured["headers"] = headers
        captured["json"] = json
        return FakeResponse(
            {
                "output": {
                    "choices": [
                        {
                            "message": {
                                "content": [
                                    {
                                        "text": '{"candidates":[{"asset_id":"ast_1","label":"榨汁杯","confidence":0.91,"reason":"主体清晰"}]}'
                                    }
                                ]
                            }
                        }
                    ]
                }
            }
        )

    monkeypatch.setattr("onetake_api.integrations.qwen_recognition.adapter.httpx.post", fake_post)
    adapter = QwenRecognitionAdapter(api_key="test-key", endpoint="https://example.test/recognize", model="qwen-vl-plus")
    candidates = adapter.recognize(
        project_name="榨汁杯",
        product_note="白色杯身",
        images=[RecognitionImage("ast_1", "product.png", "image/png", "a" * 64, _png())],
    )
    assert len(candidates) == 1
    assert candidates[0].asset_id == "ast_1"
    assert candidates[0].confidence == 0.91
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["json"]["model"] == "qwen-vl-plus"


def test_qwen_recognition_rejects_invented_asset_id(monkeypatch) -> None:
    monkeypatch.setattr(
        "onetake_api.integrations.qwen_recognition.adapter.httpx.post",
        lambda *args, **kwargs: FakeResponse(
            {
                "output": {
                    "choices": [
                        {
                            "message": {
                                "content": [
                                    {"text": '{"candidates":[{"asset_id":"ast_invented","label":"商品","confidence":0.9,"reason":"猜测"}]}'}
                                ]
                            }
                        }
                    ]
                }
            }
        ),
    )
    adapter = QwenRecognitionAdapter(api_key="test-key", endpoint="https://example.test/recognize", model="qwen-vl-plus")
    with pytest.raises(QwenRecognitionError):
        adapter.recognize(
            project_name="榨汁杯",
            product_note=None,
            images=[RecognitionImage("ast_1", "product.png", "image/png", None, _png())],
        )
