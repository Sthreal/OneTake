from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

from onetake_api.integrations.media.caption_styles import (
    LEGACY_FONT_SIZE,
    font_size_for,
    resolve_caption_style,
)
from onetake_api.integrations.media.subtitle_segmentation import (
    SubtitleCue,
    parse_srt_bytes,
    split_srt_bytes,
)
from onetake_api.platform.errors import DomainError

CAPTION_FONT_PATH = (
    Path(__file__).resolve().parents[2]
    / "assets"
    / "fonts"
    / "NotoSansSC-VariableFont_wght.ttf"
)
CAPTION_FONT_NAME = "Noto Sans SC"
# 字号已不再是"固定值"：四档样式由 caption_styles 按**帧宽比例**给出；帧宽未知时回落 LEGACY_FONT_SIZE（=16），
# 与本文件改造前的固定值一致。保留本名是为了不破坏任何按名引用的地方。
CAPTION_FONT_SIZE = LEGACY_FONT_SIZE
CAPTION_MARGIN_L = 80
CAPTION_MARGIN_R = 80
CAPTION_MARGIN_V = 60

# ASS/SSA 的脚本分辨率。**必须**与 SRT 路径（ffmpeg 给 libass 的默认头）一致，
# 否则同一档样式在两条路径上的字号/边距会不一样（1b 已实测标定过这套口径）。
ASS_PLAY_RES_X = 384
ASS_PLAY_RES_Y = 288
ASS_STYLE_NAME = "Caption"
# karaoke 两色：已唱=白、未唱=浅灰（都在黑描边上，画面里可读）
KARAOKE_SUNG_COLOUR = "&H00FFFFFF"
KARAOKE_UNSUNG_COLOUR = "&H00B0B0B0"
ASS_ALPHA_OPAQUE = "&H00000000"


class SubtitleBurnError(DomainError):
    code = "COMPOSITION_PROVIDER_ERROR"
    http_status = 502
    retryable = True


def _escape_filter_path(path) -> str:
    r"""filtergraph 里的路径必须转义 Windows 盘符冒号。

    subtitles='C:/x/sub.srt' 会被 filter 解析器当成「选项 C」而报
    「Error opening output file / Invalid argument」；正确写法是 `C\:/x/sub.srt`。
    这一条在 Windows 上是必需的，Linux/macOS 下无副作用。
    """
    return str(path).replace("\\", "/").replace(":", "\\:")


def build_force_style(*, width: int | None = None, style: str | None = None) -> str:
    """按样式预设 + 帧宽生成 libass 的 force_style 串（SRT 路径用）。

    - `width=None` / `style=None` → 与改造前**逐字相同**的串（FontSize=16、Outline=2、无底板）。
    - `karaoke` 档不走这里（它要 ASS 的 `\\k` 标签，见 `build_karaoke_ass`）。
    """
    preset = resolve_caption_style(style)
    font_size = font_size_for(width, preset)
    return (
        f"FontName={CAPTION_FONT_NAME},FontSize={font_size},"
        "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
        f"BorderStyle=1,Outline={preset.outline},Shadow=0,Alignment=2,"
        f"MarginL={CAPTION_MARGIN_L},MarginR={CAPTION_MARGIN_R},MarginV={CAPTION_MARGIN_V}"
    )


def build_karaoke_ass(*, srt_bytes: bytes, width: int | None = None, style: str | None = None) -> str:
    """SRT → ASS（逐字 karaoke）。

    `\\k` 标签必须走 ASS —— libass 的 `subtitles` 滤镜能吃 SRT，但 SRT 表达不了卡拉OK 计时。
    时长按**字符数均分**（与参考实现同源：它也是用自产 TTS 时长对齐，不是真词级），
    并做**累计取整**：每个字的持续时间 = 累计厘秒差，这样 `\\k` 之和 == 该句总时长（误差 < 10ms）。
    """
    preset = resolve_caption_style(style or "karaoke")
    font_size = font_size_for(width, preset)
    cues = parse_srt_bytes(split_srt_bytes(srt_bytes))
    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {ASS_PLAY_RES_X}",
        f"PlayResY: {ASS_PLAY_RES_Y}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: {ASS_STYLE_NAME},{CAPTION_FONT_NAME},{font_size},{KARAOKE_SUNG_COLOUR},"
        f"{KARAOKE_UNSUNG_COLOUR},{ASS_ALPHA_OPAQUE},{ASS_ALPHA_OPAQUE},0,0,0,0,100,100,0,0,1,"
        f"{preset.outline},0,2,{CAPTION_MARGIN_L},{CAPTION_MARGIN_R},{CAPTION_MARGIN_V},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    events = [
        f"Dialogue: 0,{_ass_time(cue.start_ms)},{_ass_time(cue.end_ms)},{ASS_STYLE_NAME},,0,0,0,,{_karaoke_text(cue)}"
        for cue in cues
    ]
    return "\n".join(header + events) + "\n"


def _karaoke_text(cue: SubtitleCue) -> str:
    duration_ms = max(0, cue.end_ms - cue.start_ms)
    lines = [line for line in cue.text.split("\n") if line]
    visible = [character for line in lines for character in line]
    total_chars = len(visible)
    if total_chars == 0:
        return ""
    rendered: list[str] = []
    index = 0
    previous_centiseconds = 0
    for line in lines:
        for character in line:
            index += 1
            cumulative = round(duration_ms * index / (10 * total_chars))
            centiseconds = max(0, cumulative - previous_centiseconds)
            previous_centiseconds = cumulative
            rendered.append(f"{{\\k{centiseconds}}}{_escape_ass_text(character)}")
        rendered.append("\\N")
    if rendered and rendered[-1] == "\\N":
        rendered.pop()
    return "".join(rendered)


def _escape_ass_text(text: str) -> str:
    """花括号在 ASS 里是 override 语法；文本里的花括号要转义（libass 支持 `\\{` / `\\}`）。"""
    return text.replace("{", "\\{").replace("}", "\\}")


def _ass_time(milliseconds: int) -> str:
    hours, remainder = divmod(max(0, milliseconds), 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, remainder = divmod(remainder, 1_000)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{remainder // 10:02d}"


def burn_subtitles(
    *,
    base_video_bytes: bytes,
    srt_bytes: bytes,
    duration_seconds: float,
    fps: int,
    preserve_audio: bool = False,
    width: int | None = None,
    style: str | None = None,
) -> bytes:
    """把字幕烧进视频。

    `width` / `style` 是批次 1a 新增的**全默认参数**（向后兼容）：
    - `width`：成片帧宽，用于把四档样式的字号换成"帧宽比例"；不传则保持改造前的固定字号。
    - `style`：`standard`（默认）/ `bold` / `minimal` / `karaoke`，取值与口径见 `caption_styles.py`；
      `karaoke` 走 ASS 逐字路径（批次 1c）。
    """
    if not base_video_bytes or not srt_bytes:
        raise SubtitleBurnError("字幕烧录输入为空")
    srt_bytes = split_srt_bytes(srt_bytes)
    if not CAPTION_FONT_PATH.is_file():
        raise SubtitleBurnError("中文字体资源缺失")
    preset = resolve_caption_style(style)
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        base_path = root / "base.mp4"
        font_config_path = root / "fonts.conf"
        font_cache_path = root / "font-cache"
        output_path = root / "captioned.mp4"
        base_path.write_bytes(base_video_bytes)
        if preset.karaoke:
            # karaoke：样式与 `\k` 都写在 ASS 里，不再传 force_style（否则会盖掉逐字着色）
            subtitle_path = root / "subtitle.ass"
            subtitle_path.write_text(
                build_karaoke_ass(srt_bytes=srt_bytes, width=width, style=style), encoding="utf-8"
            )
            subtitle_filter = (
                f"subtitles='{_escape_filter_path(subtitle_path)}':"
                f"fontsdir='{_escape_filter_path(CAPTION_FONT_PATH.parent)}'"
            )
        else:
            subtitle_path = root / "subtitle.srt"
            subtitle_path.write_bytes(srt_bytes)
            subtitle_filter = (
                f"subtitles='{_escape_filter_path(subtitle_path)}':"
                f"fontsdir='{_escape_filter_path(CAPTION_FONT_PATH.parent)}':"
                f"force_style='{build_force_style(width=width, style=style)}'"
            )
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