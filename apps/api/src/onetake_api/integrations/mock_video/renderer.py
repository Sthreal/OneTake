from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

from onetake_api.platform.errors import DomainError

MAX_OUTPUT_BYTES = 30 * 1024 * 1024


class MockVideoError(DomainError):
    code = "VIDEO_PROVIDER_ERROR"
    http_status = 502
    retryable = True


@dataclass(frozen=True)
class VideoMetadata:
    duration_seconds: float
    width: int
    height: int
    fps: float
    video_codec: str
    audio_codec: str | None


def _run(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            [get_ffmpeg_exe(), *command],
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stderr
    except subprocess.CalledProcessError as exc:
        raise MockVideoError((exc.stderr or "ffmpeg failed")[-300:]) from exc
    except OSError as exc:
        raise MockVideoError("ffmpeg 不可用") from exc


def render_base_video(
    *,
    image_bytes: bytes,
    mode: str,
    template_id: str | None,
    duration_seconds: float,
    width: int,
    height: int,
    fps: int,
) -> bytes:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        image_path = root / "main.png"
        output_path = root / "base.mp4"
        image_path.write_bytes(image_bytes)
        layout_filter = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=white,"
            "format=yuv420p"
        )
        if mode == "product" and template_id == "dynamic":
            layout_filter += f",fade=t=in:st=0:d=1,fade=t=out:st={max(0.0, duration_seconds - 1):.3f}:d=1"
        command = [
            "-y", "-loop", "1", "-i", str(image_path),
            "-vf", layout_filter, "-t", f"{duration_seconds:.3f}", "-r", str(fps),
            "-an", "-c:v", "libx264", "-b:v", "8M", "-pix_fmt", "yuv420p", str(output_path),
        ]
        _run(command)
        return output_path.read_bytes()


def compose_final_video(
    *,
    base_video_bytes: bytes,
    audio_bytes: bytes | None,
    srt_bytes: bytes | None,
    duration_seconds: float,
    fps: int,
) -> bytes:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        base_path = root / "base.mp4"
        output_path = root / "final.mp4"
        base_path.write_bytes(base_video_bytes)
        command = ["-y", "-i", str(base_path)]
        input_index = 1
        audio_index = None
        subtitle_index = None
        if audio_bytes:
            audio_path = root / "voice.wav"
            audio_path.write_bytes(audio_bytes)
            command += ["-i", str(audio_path)]
            audio_index = input_index
            input_index += 1
        if srt_bytes:
            subtitle_path = root / "subtitle.srt"
            subtitle_path.write_bytes(srt_bytes)
            command += ["-i", str(subtitle_path)]
            subtitle_index = input_index
        command += ["-map", "0:v:0"]
        if audio_index is not None:
            command += ["-map", f"{audio_index}:a:0"]
        if subtitle_index is not None:
            command += ["-map", f"{subtitle_index}:s:0"]
        command += ["-t", f"{duration_seconds:.3f}", "-r", str(fps), "-c:v", "libx264", "-b:v", "8M", "-pix_fmt", "yuv420p"]
        if audio_index is not None:
            command += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
        else:
            command += ["-an"]
        if subtitle_index is not None:
            command += ["-c:s", "mov_text", "-metadata:s:s:0", "language=chi"]
        command += [str(output_path)]
        _run(command)
        return output_path.read_bytes()


def inspect_video(video_bytes: bytes) -> VideoMetadata:
    with tempfile.TemporaryDirectory() as temp_dir:
        input_path = Path(temp_dir) / "video.mp4"
        input_path.write_bytes(video_bytes)
        stderr = _run(["-hide_banner", "-i", str(input_path), "-map", "0:v:0", "-map", "0:a?", "-f", "null", "-"])
        duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
        video_line = next((line for line in stderr.splitlines() if " Video: " in line), None)
        if duration_match is None or video_line is None:
            raise MockVideoError("无法读取视频元数据")
        codec_match = re.search(r"Video:\s*([^,\s]+)", video_line)
        size_match = re.search(r"(\d{2,5})x(\d{2,5})", video_line)
        fps_match = re.search(r"([\d.]+)\s*fps", video_line)
        if codec_match is None or size_match is None or fps_match is None:
            raise MockVideoError("视频元数据不完整")
        audio_line = next((line for line in stderr.splitlines() if " Audio: " in line), None)
        audio_codec = None
        if audio_line is not None:
            audio_match = re.search(r"Audio:\s*([^,\s]+)", audio_line)
            if audio_match is None:
                raise MockVideoError("音频元数据不完整")
            audio_codec = audio_match.group(1).lower()
        hours, minutes, seconds = duration_match.groups()
        return VideoMetadata(
            duration_seconds=int(hours) * 3600 + int(minutes) * 60 + float(seconds),
            width=int(size_match.group(1)),
            height=int(size_match.group(2)),
            fps=float(fps_match.group(1)),
            video_codec=codec_match.group(1).lower(),
            audio_codec=audio_codec,
        )


def validate_final_video(
    video_bytes: bytes,
    *,
    expected_width: int,
    expected_height: int,
    expected_fps: int,
    expected_audio: bool,
) -> VideoMetadata:
    if not video_bytes:
        raise MockVideoError("成片为空")
    if len(video_bytes) > MAX_OUTPUT_BYTES:
        raise MockVideoError("成片超过 30 MB")
    metadata = inspect_video(video_bytes)
    if metadata.width != expected_width or metadata.height != expected_height:
        raise MockVideoError(f"成片分辨率错误：{metadata.width}x{metadata.height}")
    if not 18 <= metadata.duration_seconds <= 25:
        raise MockVideoError(f"成片时长超出范围：{metadata.duration_seconds:.2f}s")
    if abs(metadata.fps - expected_fps) > 0.1:
        raise MockVideoError(f"成片帧率错误：{metadata.fps:g}fps")
    if metadata.video_codec != "h264":
        raise MockVideoError(f"成片视频编码错误：{metadata.video_codec}")
    if expected_audio and metadata.audio_codec != "aac":
        raise MockVideoError("成片音频编码错误")
    return metadata
