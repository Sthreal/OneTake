from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

from onetake_api.platform.errors import DomainError


class VideoProcessingError(DomainError):
    code = "VIDEO_PROCESSING_ERROR"
    http_status = 502
    retryable = True


def concatenate_videos(*, clips: list[bytes], duration_seconds: float, fps: int) -> bytes:
    if not clips:
        raise VideoProcessingError("没有可拼接的视频片段")
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        paths = []
        for index, clip in enumerate(clips):
            path = root / f"clip-{index}.mp4"
            path.write_bytes(clip)
            paths.append(path)
        list_path = root / "clips.txt"
        list_path.write_text("".join(f"file '{path.as_posix()}'\n" for path in paths), encoding="utf-8")
        output = root / "combined.mp4"
        try:
            subprocess.run(
                [get_ffmpeg_exe(), "-y", "-f", "concat", "-safe", "0", "-i", str(list_path), "-t", f"{duration_seconds:.3f}", "-r", str(fps), "-an", "-c:v", "libx264", "-b:v", "8M", "-pix_fmt", "yuv420p", str(output)],
                check=True,
                capture_output=True,
                text=True,
            )
        except (subprocess.CalledProcessError, OSError) as exc:
            raise VideoProcessingError("视频片段拼接失败") from exc
        return output.read_bytes()
