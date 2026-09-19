import json
from io import BytesIO

import httpx
from PIL import Image

from onetake_api.integrations.qwen_vl_quality.adapter import QwenVlSemanticAdapter
from onetake_api.modules.content_plan.domain import ContentPlan, ContentScene, ContentVariant
from onetake_api.modules.content_qa.domain import QaRequest


def _png(color: str) -> bytes:
    output = BytesIO()
    Image.new("RGB", (600, 800), color).save(output, format="PNG")
    return output.getvalue()


def test_qwen_vl_semantic_adapter_parses_strict_json(monkeypatch) -> None:
    now = __import__("datetime").datetime.now(__import__("datetime").UTC)
    scene = ContentScene("scene_1", 1, "hook", "文案", 0, 18, "product_motion", "保持商品不变", True, "center", "clean", "clean", [1], ["product_visible"])
    plan = ContentPlan("cpl_1", "prj_1", "scr_1", "sub_1", "confirmed", "rules", "rules-v1", [ContentVariant("var_clean", "干净展示", "clean", [scene])], 0, 18, None, now, now, now)
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        images = [item for item in payload["input"]["messages"][0]["content"] if "image" in item]
        assert len(images) == 3
        content = json.dumps({"score": 92, "passed": True, "issues": [], "checks": [{"check_id": "product_consistency", "label": "商品一致性", "passed": True, "weight": 30, "message": "商品保持一致"}]}, ensure_ascii=False)
        return httpx.Response(200, json={"output": {"choices": [{"message": {"content": content}}]}})
    adapter = QwenVlSemanticAdapter(api_key="key", endpoint="https://example.test/qwen", model="qwen-vl-plus", frame_count=3, client=httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(adapter, "_extract_frames", lambda *_args: [_png("white"), _png("white")])
    result = adapter.evaluate(QaRequest(plan=plan, metadata=type("M", (), {"duration_seconds": 18})(), size_bytes=1000, expected_audio=True, subtitle_embedded=True, product_layered=True, video_bytes=b"video", product_image_bytes=_png("red")))
    assert result.score == 92
    assert result.passed is True
    assert result.checks[0].check_id == "product_consistency"
