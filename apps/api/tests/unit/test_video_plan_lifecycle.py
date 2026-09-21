from onetake_api.modules.video_plan.service import REGENERABLE_PIPELINE_STATUSES


def test_video_plan_allows_confirmed_content_plan() -> None:
    assert "content_plan_confirmed" in REGENERABLE_PIPELINE_STATUSES
    assert "content_qa_passed" in REGENERABLE_PIPELINE_STATUSES