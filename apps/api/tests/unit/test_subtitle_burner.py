import subprocess
import tempfile
from pathlib import Path

from PIL import Image
from imageio_ffmpeg import get_ffmpeg_exe

from onetake_api.integrations.media.subtitle_burner import burn_subtitles


def _black_video(root: Path) -> bytes:
    output = root / "black.mp4"
    subprocess.run(
        [
            get_ffmpeg_exe(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=360x640:d=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return output.read_bytes()


def test_burn_subtitles_renders_chinese_pixels() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        base = _black_video(root)
        captioned = burn_subtitles(
            base_video_bytes=base,
            srt_bytes="1\n00:00:00,000 --> 00:00:01,500\n测试字幕\n".encode("utf-8"),
            duration_seconds=2,
            fps=25,
        )
        video = root / "captioned.mp4"
        frame = root / "frame.png"
        video.write_bytes(captioned)
        subprocess.run(
            [get_ffmpeg_exe(), "-y", "-ss", "0.5", "-i", str(video), "-frames:v", "1", str(frame)],
            check=True,
            capture_output=True,
            text=True,
        )
        image = Image.open(frame).convert("RGB")
        white_pixels = sum(1 for red, green, blue in image.getdata() if red > 180 and green > 180 and blue > 180)
        assert white_pixels > 100
