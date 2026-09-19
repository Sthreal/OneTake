import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageStat
from imageio_ffmpeg import get_ffmpeg_exe

import onetake_api.integrations.mock_video.renderer as renderer
from onetake_api.integrations.mock_video.renderer import (
    compose_final_video,
    inspect_video,
    render_base_video,
    validate_final_video,
)


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


def _centered_rect_png() -> bytes:
    output = BytesIO()
    image = Image.new("RGB", (600, 800), (255, 255, 255))
    ImageDraw.Draw(image).rectangle((150, 200, 450, 600), fill=(20, 20, 20))
    image.save(output, format="PNG")
    return output.getvalue()


def _content_box(frame: Image.Image) -> tuple[int, int, int, int]:
    white = Image.new("RGB", frame.size, (255, 255, 255))
    mask = ImageChops.difference(frame, white).convert("L").point(lambda value: 255 if value > 20 else 0)
    box = mask.getbbox()
    assert box is not None
    return box


def test_dynamic_template_uses_supersampling_before_downscale(monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str]) -> str:
        commands.append(command)
        Path(command[-1]).write_bytes(b"ftypstub")
        return ""

    monkeypatch.setattr(renderer, "_run", fake_run)
    renderer.render_base_video(image_bytes=_png(), mode="product", template_id="dynamic", duration_seconds=1.0, width=360, height=640, fps=30)

    filter_graph = commands[0][commands[0].index("-vf") + 1]
    assert "zoompan=z='min(1+" in filter_graph
    assert "s=720x1280" in filter_graph
    assert "scale=360:640:flags=lanczos" in filter_graph


def test_dynamic_template_has_monotonic_zoom_motion() -> None:
    video = render_base_video(image_bytes=_centered_rect_png(), mode="product", template_id="dynamic", duration_seconds=3.0, width=360, height=640, fps=30)
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        video_path = root / "video.mp4"
        video_path.write_bytes(video)
        boxes = []
        for index, seconds in enumerate((1.1, 1.35, 1.6, 1.85)):
            frame_path = root / f"motion-{index}.png"
            subprocess.run([get_ffmpeg_exe(), "-y", "-ss", str(seconds), "-i", str(video_path), "-frames:v", "1", str(frame_path)], check=True, capture_output=True, text=True)
            boxes.append(_content_box(Image.open(frame_path).convert("RGB")))

    widths = [box[2] - box[0] for box in boxes]
    heights = [box[3] - box[1] for box in boxes]
    assert widths == sorted(widths)
    assert heights == sorted(heights)
    assert widths[-1] > widths[0]
    assert heights[-1] > heights[0]


def test_dynamic_template_has_visible_zoom_motion() -> None:
    video = render_base_video(image_bytes=_png(), mode="product", template_id="dynamic", duration_seconds=2.0, width=360, height=640, fps=30)
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        video_path = root / "video.mp4"
        video_path.write_bytes(video)
        frames = []
        for index, seconds in enumerate((0.1, 1.9)):
            frame_path = root / f"frame-{index}.png"
            subprocess.run([get_ffmpeg_exe(), "-y", "-ss", str(seconds), "-i", str(video_path), "-frames:v", "1", str(frame_path)], check=True, capture_output=True, text=True)
            frames.append(Image.open(frame_path).convert("RGB"))
        diff = ImageChops.difference(frames[0], frames[1])
        assert sum(ImageStat.Stat(diff).mean) / 3 > 0.5
