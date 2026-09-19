from onetake_api.integrations.mock_video.renderer import VideoMetadata
from onetake_api.modules.content_plan.domain import ContentPlan, ContentScene, ContentVariant
from onetake_api.modules.content_qa.domain import QaRequest
from onetake_api.modules.content_qa.rules import RuleContentQaAdapter


def _plan() -> ContentPlan:
    scene = ContentScene("scene_1", 1, "hook", "测试文案", 0.0, 18.0, "product_motion", "保持商品不变", True, "center", "clean", "clean", [1], ["product_visible"])
    return ContentPlan("cpl_1", "prj_1", "scr_1", "sub_1", "confirmed", "rules", "rules-v1", [ContentVariant("var_clean", "干净展示", "clean", [scene])], 0, 18.0, None, __import__("datetime").datetime.now(__import__("datetime").UTC), __import__("datetime").datetime.now(__import__("datetime").UTC), __import__("datetime").datetime.now(__import__("datetime").UTC))


def test_rule_checks_reject_missing_product_and_black_frames() -> None:
    request = QaRequest(plan=_plan(), metadata=VideoMetadata(18.0, 1080, 1920, 30.0, "h264", "aac"), size_bytes=1000, expected_audio=True, subtitle_embedded=True, product_layered=False, video_bytes=b"not-video")
    result = RuleContentQaAdapter().evaluate(request)
    assert result.passed is False
    assert "product_layer" in result.critical_failures
    assert "black_frames" in result.critical_failures
