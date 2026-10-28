"""S6 6e 单测：模型能力表与预检（能力表的每条都要有出处，不许凭印象）。"""
from __future__ import annotations

import pytest

from onetake_api.integrations.media.model_capabilities import (
    CAPABILITIES,
    MODEL_I2V,
    MODEL_KF2V,
    MODEL_R2V,
    preflight,
    resolve_model_kind,
)


def test_every_capability_row_cites_a_source() -> None:
    for key, caps in CAPABILITIES.items():
        assert caps.key == key
        assert caps.label
        assert caps.source.startswith(("integrations/", "video_plan/"))


def test_kf2v_is_the_only_model_taking_a_last_frame() -> None:
    assert CAPABILITIES[MODEL_KF2V].last_frame is True
    assert CAPABILITIES[MODEL_I2V].last_frame is False
    assert CAPABILITIES[MODEL_R2V].last_frame is False


def test_r2v_limits_come_from_the_code_constants_not_from_memory() -> None:
    from onetake_api.modules.video_plan.one_shot import MAX_CALL_SECONDS, MAX_REFERENCE_IMAGES

    caps = CAPABILITIES[MODEL_R2V]
    assert caps.max_call_seconds == MAX_CALL_SECONDS
    assert caps.reference_images == MAX_REFERENCE_IMAGES


@pytest.mark.parametrize(
    ("path", "seam", "expected"),
    [
        ("one_shot", "pin", MODEL_R2V),
        ("segmented", "pin", MODEL_KF2V),
        ("segmented", "tail", MODEL_I2V),
        ("segmented", "off", MODEL_I2V),
    ],
)
def test_model_resolution_follows_the_anchor_branches(path: str, seam: str, expected: str) -> None:
    assert resolve_model_kind(path=path, seam_mode=seam) == expected


def test_over_long_single_call_warns_about_splitting() -> None:
    codes = [item.code for item in preflight(
        model_kind=MODEL_R2V, duration_seconds=18, shot_count=4, seam_mode="pin", path="one_shot"
    )]
    assert "duration-split-required" in codes


def test_too_many_shots_warns_about_the_media_limit() -> None:
    codes = [item.code for item in preflight(
        model_kind=MODEL_R2V, duration_seconds=14, shot_count=6, seam_mode="pin", path="one_shot"
    )]
    assert "media-over-limit" in codes


def test_seam_warnings_are_suppressed_on_the_one_shot_path() -> None:
    codes = [item.code for item in preflight(
        model_kind=MODEL_R2V, duration_seconds=14, shot_count=4, seam_mode="pin", path="one_shot"
    )]
    assert "last-frame-unsupported" not in codes


def test_segmented_pin_does_not_warn_because_kf2v_takes_the_last_frame() -> None:
    codes = [item.code for item in preflight(
        model_kind=MODEL_KF2V, duration_seconds=14, shot_count=4, seam_mode="pin", path="segmented"
    )]
    assert "last-frame-unsupported" not in codes


def test_unknown_model_is_reported_and_not_guessed() -> None:
    checks = preflight(
        model_kind="brand-new-model", duration_seconds=14, shot_count=4, seam_mode="pin", path="segmented"
    )
    assert [item.code for item in checks] == ["unknown-model"]
    assert checks[0].level == "warn"
