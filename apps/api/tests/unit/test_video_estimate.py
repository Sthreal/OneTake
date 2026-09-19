from types import SimpleNamespace

from onetake_api.config import Settings
from onetake_api.modules.video_plan.estimate import estimate_video_generation


def _plan(*, mode: str = "product", template_id: str | None = "dynamic", duration_seconds: float = 18.0):
    return SimpleNamespace(id="vid_test", mode=mode, template_id=template_id, duration_seconds=duration_seconds)


def test_dynamic_real_estimate_counts_wan_clips_and_missing_prices() -> None:
    settings = Settings(
        mock_providers=False,
        product_scene_enabled=True,
        image_edit_provider="real",
        wan_i2v_provider="real",
        composition_provider="shotstack",
        wan_i2v_max_seconds=5,
        wan_i2v_price_per_second=0.15,
        qwen_image_edit_price_per_call=None,
        shotstack_render_price=None,
        video_estimate_minutes_per_clip=1.0,
        video_estimate_overhead_minutes=0.5,
    )

    estimate = estimate_video_generation(_plan(duration_seconds=18), settings)

    assert estimate.wan_clip_count == 4
    assert estimate.wan_generated_seconds == 20
    assert estimate.estimated_wan_cost == 3.0
    assert estimate.qwen_image_edit_calls == 1
    assert estimate.shotstack_renders == 1
    assert estimate.requires_confirmation is True
    assert set(estimate.missing_price_config) == {"QWEN_IMAGE_EDIT_PRICE_PER_CALL", "SHOTSTACK_RENDER_PRICE"}


def test_mock_estimate_does_not_require_confirmation() -> None:
    settings = Settings(mock_providers=True, wan_i2v_provider="mock", composition_provider="mock")
    estimate = estimate_video_generation(_plan(), settings)
    assert estimate.is_paid is False
    assert estimate.requires_confirmation is False
    assert estimate.wan_clip_count == 0
    assert estimate.estimated_known_cost == 0.0


def test_estimate_rounds_partial_clip_up() -> None:
    settings = Settings(
        mock_providers=False,
        product_scene_enabled=True,
        image_edit_provider="real",
        wan_i2v_provider="real",
        composition_provider="shotstack",
        wan_i2v_max_seconds=5,
        wan_i2v_price_per_second=0.15,
    )
    estimate = estimate_video_generation(_plan(duration_seconds=12.1), settings)
    assert estimate.wan_clip_count == 3
    assert estimate.wan_generated_seconds == 15
