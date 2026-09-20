import json

import httpx

from onetake_api.integrations.qwen_creative.adapter import QwenCreativePlanner
from onetake_api.modules.content_plan.generator import generate_rule_variants


def test_qwen_creative_only_updates_visual_fields() -> None:
    variants = generate_rule_variants(segments=[{"index": 1, "text": "第一句", "start": 0, "end": 2}, {"index": 2, "text": "第二句", "start": 2, "end": 4}])
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode('utf-8'))
        assert "不得修改文案" in payload["input"]["messages"][0]["content"]
        response = {"variants": []}
        for variant in variants:
            response["variants"].append({"variant_id": variant.variant_id, "scenes": [{"scene_id": scene.scene_id, "prompt": f"创意-{scene.scene_id}", "shot_type": "product_motion", "background_style": "studio"} for scene in variant.scenes]})
        content = json.dumps(response, ensure_ascii=False)
        return httpx.Response(200, json={"output": {"choices": [{"message": {"content": content}}]}})
    planner = QwenCreativePlanner(api_key="key", endpoint="https://example.test/qwen", model="qwen-plus", client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = planner.enhance(variants=variants, facts={"product_name": "榨汁杯"})
    assert result[0].scenes[0].start_seconds == 0
    assert result[0].scenes[0].script_excerpt == "第一句第二句"
    assert result[0].scenes[0].prompt == "创意-scene_1"
