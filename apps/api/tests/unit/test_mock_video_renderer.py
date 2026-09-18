from io import BytesIO

from PIL import Image

from onetake_api.integrations.mock_video.renderer import compose_final_video, inspect_video, render_base_video, validate_final_video


def _png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (600, 800), (240, 90, 30)).save(output, format="PNG")
    return output.getvalue()


def test_mock_video_renderer_outputs_mp4() -> None:
    base = render_base_video(image_bytes=_png(), mode="product", template_id="clean", duration_seconds=0.8, width=360, height=640, fps=24)
    final = compose_final_video(base_video_bytes=base, audio_bytes=None, srt_bytes=None, duration_seconds=0.8, fps=24)
    assert len(base) > 1000
    assert len(final) > 1000
    assert b"ftyp" in final[:32]


def test_mock_video_metadata_can_be_inspected() -> None:
    base = render_base_video(image_bytes=_png(), mode="product", template_id="clean", duration_seconds=1.0, width=360, height=640, fps=30)
    final = compose_final_video(base_video_bytes=base, audio_bytes=None, srt_bytes=None, duration_seconds=1.0, fps=30)
    metadata = inspect_video(final)
    assert metadata.width == 360
    assert metadata.height == 640
    assert metadata.fps == 30
    assert metadata.video_codec == "h264"
    assert metadata.audio_codec is None


def test_final_video_validation_rejects_wrong_spec() -> None:
    base = render_base_video(image_bytes=_png(), mode="product", template_id="clean", duration_seconds=1.0, width=360, height=640, fps=30)
    final = compose_final_video(base_video_bytes=base, audio_bytes=None, srt_bytes=None, duration_seconds=1.0, fps=30)
    try:
        validate_final_video(final, expected_width=1080, expected_height=1920, expected_fps=30, expected_audio=True)
    except Exception as exc:
        assert "分辨率错误" in str(exc)
    else:
        raise AssertionError("invalid final video should be rejected")
