from types import SimpleNamespace

import pytest

from onetake_api.modules.video_plan.service import VideoPlanApplicationService, VideoPlanConflictError


def test_create_base_video_routes_avatar_to_s2v(monkeypatch) -> None:
    import onetake_api.modules.video_plan.service as service_module

    settings = SimpleNamespace(
        mock_providers=False,
        avatar_video_provider="real",
        composition_provider="shotstack",
        dashscope_api_key="key",
        wan_s2v_model="wan2.2-s2v",
        wan_s2v_avatar_path="avatar.png",
        shotstack_api_key="key",
    )
    monkeypatch.setattr(service_module, "get_settings", lambda: settings)
    service = VideoPlanApplicationService(composition=SimpleNamespace(provider_name="shotstack"))
    calls = []
    monkeypatch.setattr(service, "_create_avatar_video", lambda plan, audio: calls.append((plan, audio)) or b"avatar-video")

    plan = SimpleNamespace(mode="avatar")
    assert service._create_base_video(None, plan, b"main-image", b"voice") == b"avatar-video"
    assert calls == [(plan, b"voice")]


def test_create_base_video_rejects_incomplete_avatar_config(monkeypatch) -> None:
    import onetake_api.modules.video_plan.service as service_module

    settings = SimpleNamespace(
        mock_providers=False,
        avatar_video_provider="real",
        composition_provider="shotstack",
        dashscope_api_key="",
        wan_s2v_model="",
        wan_s2v_avatar_path="",
        shotstack_api_key="",
    )
    monkeypatch.setattr(service_module, "get_settings", lambda: settings)
    service = VideoPlanApplicationService(composition=SimpleNamespace(provider_name="shotstack"))

    with pytest.raises(VideoPlanConflictError, match="有人视频真实链路配置不完整"):
        service._create_base_video(None, SimpleNamespace(mode="avatar"), b"main-image", b"voice")


def test_silent_wav_has_expected_duration_header() -> None:
    import wave
    from io import BytesIO

    payload = VideoPlanApplicationService._silent_wav(1.0)
    with wave.open(BytesIO(payload), "rb") as wav:
        assert wav.getframerate() == 48000
        assert wav.getnchannels() == 1
        assert wav.getnframes() == 48000

def test_create_base_video_uses_mock_avatar_asset(monkeypatch) -> None:
    import onetake_api.modules.video_plan.service as service_module

    settings = SimpleNamespace(mock_providers=True, avatar_video_provider="mock")
    monkeypatch.setattr(service_module, "get_settings", lambda: settings)
    monkeypatch.setattr(service_module, "load_mock_avatar", lambda: b"mock-avatar")
    calls = []

    def fake_render_base_video(*, image_bytes, **_kwargs):
        calls.append(image_bytes)
        return b"base-video"

    monkeypatch.setattr(service_module, "render_base_video", fake_render_base_video)
    service = VideoPlanApplicationService(composition=SimpleNamespace(provider_name="mock-video"))
    plan = SimpleNamespace(
        mode="avatar",
        template_id=None,
        duration_seconds=18,
        width=1080,
        height=1920,
        fps=30,
    )

    assert service._create_base_video(None, plan, b"main-image", b"voice") == b"base-video"
    assert calls == [b"mock-avatar"]


def test_mock_avatar_asset_is_available() -> None:
    from onetake_api.integrations.product_scene.avatar_assets import load_mock_avatar

    assert load_mock_avatar()
