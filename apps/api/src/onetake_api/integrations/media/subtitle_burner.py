from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

from onetake_api.integrations.media.subtitle_segmentation import split_srt_bytes
from onetake_api.platform.errors import DomainError

CAPTION_FONT_PATH = (
    Path(__file__).resolve().parents[2]
    / "assets"
    / "fonts"
    / "NotoSansSC-VariableFont_wght.ttf"
)
CAPTION_FONT_NAME = "Noto Sans SC"
CAPTION_FONT_SIZE = 16
CAPTION_MARGIN_L = 80
CAPTION_MARGIN_R = 80
CAPTION_MARGIN_V = 60


class SubtitleBurnError(DomainError):
    code = "COMPOSITION_PROVIDER_ERROR"
    http_status = 502
    retryable = True


def burn_subtitles(
    *,
    base_video_bytes: bytes,
    srt_bytes: bytes,
    duration_seconds: float,
    fps: int,
    preserve_audio: bool = False,
) -> bytes:
    if not base_video_bytes or not srt_bytes:
        raise SubtitleBurnError("字幕烧录输入为空")
    srt_bytes = split_srt_bytes(srt_bytes)
    if not CAPTION_FONT_PATH.is_file():
        raise SubtitleBurnError("中文字体资源缺失")
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        base_path = root / "base.mp4"
        subtitle_path = root / "subtitle.srt"
        font_config_path = root / "fonts.conf"
        font_cache_path = root / "font-cache"
        output_path = root / "captioned.mp4"
        base_path.write_bytes(base_video_bytes)
        subtitle_path.write_bytes(srt_bytes)
        font_cache_path.mkdir()
        font_config_path.write_text(
            "<?xml version=\"1.0\"?>\n"
            "<!DOCTYPE fontconfig SYSTEM \"fonts.dtd\">\n"
            "<fontconfig>\n"
            f"  <dir>{CAPTION_FONT_PATH.parent}</dir>\n"
            f"  <cachedir>{font_cache_path}</cachedir>\n"
            "</fontconfig>\n",
            encoding="utf-8",
        )
        style = (
            f"FontName={CAPTION_FONT_NAME},FontSize={CAPTION_FONT_SIZE},"
            "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
            f"BorderStyle=1,Outline=2,Shadow=0,Alignment=2,"
            f"MarginL={CAPTION_MARGIN_L},MarginR={CAPTION_MARGIN_R},MarginV={CAPTION_MARGIN_V}"
        )
        subtitle_filter = (
            f"subtitles='{subtitle_path}':fontsdir='{CAPTION_FONT_PATH.parent}':"
            f"force_style='{style}'"
        )
        command = [
            get_ffmpeg_exe(),
            "-y",
            "-i",
            str(base_path),
            "-vf",
            subtitle_filter,
            "-t",
            f"{duration_seconds:.3f}",
            "-r",
            str(fps),
        ]
        if preserve_audio:
            command += ["-map", "0:v:0", "-map", "0:a:0?"]
        else:
            command += ["-an"]
        command += ["-c:v", "libx264", "-b:v", "8M", "-pix_fmt", "yuv420p"]
        if preserve_audio:
            command += ["-c:a", "copy"]
        command += [str(output_path)]
        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                env={**os.environ, "FONTCONFIG_FILE": str(font_config_path)},
            )
        except (subprocess.CalledProcessError, OSError) as exc:
            raise SubtitleBurnError("字幕烧录失败") from exc
        return output_path.read_bytes()
