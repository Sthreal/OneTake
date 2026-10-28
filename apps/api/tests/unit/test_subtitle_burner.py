import re
import subprocess
import tempfile
from pathlib import Path

import pytest
from PIL import Image
from imageio_ffmpeg import get_ffmpeg_exe

from onetake_api.integrations.media.caption_styles import (
    CAPTION_STYLE_KEYS,
    CaptionStyleError,
)
from onetake_api.integrations.media.subtitle_burner import (
    build_force_style,
    build_karaoke_ass,
    burn_subtitles,
)


def _black_video(root: Path, *, width: int = 360, height: int = 640) -> bytes:
    output = root / f"black-{width}x{height}.mp4"
    subprocess.run(
        [
            get_ffmpeg_exe(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s={width}x{height}:d=2",
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


def _frame(root: Path, video_bytes: bytes, *, tag: str, seconds: float = 0.5) -> Image.Image:
    video = root / f"{tag}.mp4"
    frame = root / f"{tag}.png"
    video.write_bytes(video_bytes)
    subprocess.run(
        [get_ffmpeg_exe(), "-y", "-ss", f"{seconds:.3f}", "-i", str(video), "-frames:v", "1", str(frame)],
        check=True,
        capture_output=True,
        text=True,
    )
    with Image.open(frame) as image:
        return image.convert("RGB").copy()


def _ink_box(root: Path, video_bytes: bytes, *, tag: str, seconds: float = 0.5) -> tuple[int, int, int, int]:
    """字墨包围盒（用来断言两条渲染路径的几何一致性）。"""
    image = _frame(root, video_bytes, tag=tag, seconds=seconds).convert("L")
    box = image.point(lambda value: 255 if value > 60 else 0).getbbox()
    assert box is not None, "渲染出来的帧里没有任何字"
    return box


def _white_pixels(root: Path, video_bytes: bytes, *, tag: str) -> int:
    image = _frame(root, video_bytes, tag=tag)
    return sum(1 for red, green, blue in image.getdata() if red > 180 and green > 180 and blue > 180)


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
        assert _white_pixels(root, captioned, tag="captioned") > 100


def test_burn_subtitles_uses_smaller_lower_style(monkeypatch) -> None:
    captured: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs):
        captured.append(command)
        Path(command[-1]).write_bytes(b"captioned")
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr("onetake_api.integrations.media.subtitle_burner.subprocess.run", fake_run)
    result = burn_subtitles(
        base_video_bytes=b"base",
        srt_bytes="1\n00:00:00,000 --> 00:00:01,500\n测试字幕\n".encode("utf-8"),
        duration_seconds=2,
        fps=25,
    )

    assert result == b"captioned"
    filter_graph = captured[0][captured[0].index("-vf") + 1]
    assert "FontSize=16" in filter_graph
    assert "MarginL=80" in filter_graph
    assert "MarginR=80" in filter_graph
    assert "MarginV=60" in filter_graph


def test_burn_subtitles_can_preserve_audio(monkeypatch) -> None:
    captured: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs):
        captured.append(command)
        Path(command[-1]).write_bytes(b"captioned")
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr("onetake_api.integrations.media.subtitle_burner.subprocess.run", fake_run)
    result = burn_subtitles(
        base_video_bytes=b"base",
        srt_bytes="1\n00:00:00,000 --> 00:00:01,500\n测试字幕\n".encode("utf-8"),
        duration_seconds=2,
        fps=25,
        preserve_audio=True,
    )

    assert result == b"captioned"
    command = captured[0]
    assert "-an" not in command
    assert "0:a:0?" in command
    assert "copy" in command


# ---- 批次 1a：四档样式 + 帧宽比例字号 ----


def test_default_force_style_is_byte_identical_to_legacy() -> None:
    """默认档必须与改造前**逐字相同** —— 这是"默认零可见变更"的锁。"""
    legacy = (
        "FontName=Noto Sans SC,FontSize=16,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
        "BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginL=80,MarginR=80,MarginV=60"
    )
    assert build_force_style() == legacy
    # 显式选默认档 + 生产帧宽（1080）也必须落在同一个串上（防止"显式选了默认反而变了样"）
    assert build_force_style(width=1080, style="standard") == legacy


def test_caption_font_size_is_proportional_to_frame_width() -> None:
    """字号随帧宽等比变化（1080→16、720→11、540→8），不再是写死的 16。"""
    assert "FontSize=16" in build_force_style(width=1080)
    assert "FontSize=11" in build_force_style(width=720)   # 720×16/1080 = 10.67 → 11
    assert "FontSize=8" in build_force_style(width=540)    # 540×16/1080 = 8.0
    # 帧宽未知 → 回落改造前的固定值（老调用逐字不变）
    assert "FontSize=16" in build_force_style(width=None)


def test_bold_and_minimal_keep_relative_geometry() -> None:
    """四档只按**相对比例**缩放：bold 更大更粗、minimal 更小更细，standard = 现有默认。"""
    standard = build_force_style(width=1080, style="standard")
    bold = build_force_style(width=1080, style="bold")
    minimal = build_force_style(width=1080, style="minimal")
    assert "FontSize=16" in standard and "Outline=2" in standard
    assert "FontSize=20" in bold and "Outline=4" in bold           # 16×1.24、描边 4
    assert "FontSize=13" in minimal and "Outline=1" in minimal     # 16×0.84、描边 1


def test_unknown_caption_style_fails_loud() -> None:
    """未知样式不许静默回落（否则"选了没生效"会变成看不见的 bug）。"""
    with pytest.raises(CaptionStyleError) as error:
        build_force_style(style="fancy")
    assert error.value.http_status == 400
    assert error.value.retryable is False
    assert "fancy" in str(error.value)


# ---- 批次 1c：karaoke（ASS 逐字）----


def _karaoke_centiseconds(ass: str) -> list[int]:
    return [int(value) for value in re.findall(r"\\k(\d+)", ass)]


def test_karaoke_ass_timing_sums_to_cue_duration() -> None:
    """验收 4：ASS 里 `\\k` 之和 == 该句时长（累计取整，误差 < 10ms）。"""
    ass = build_karaoke_ass(srt_bytes="1\n00:00:00,000 --> 00:00:02,000\n今天这支口红\n".encode("utf-8"), width=1080)
    values = _karaoke_centiseconds(ass)
    assert len(values) == 6, values                       # 6 个字，每个一个字一段 \k
    assert abs(sum(values) * 10 - 2000) <= 10, (values, sum(values) * 10)
    dialogue = next(line for line in ass.splitlines() if line.startswith("Dialogue:"))
    assert ",0:00:00.00,0:00:02.00," in dialogue          # 起止时间与 cue 一致


def _dialogue_ms(value: str) -> int:
    hours, minutes, rest = value.split(":")
    seconds, centiseconds = rest.split(".")
    return ((int(hours) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int(centiseconds) * 10


def test_karaoke_split_lines_keep_timing_and_line_breaks() -> None:
    """折行：换行用 `\\N` 表达（不占 `\\k` 时长）；**每句**的 `\\k` 之和 == 该句自己的时长。"""
    # 12 个字 → 生产口径会切成两句，其中一句被折成两行（>10 字才折）
    ass = build_karaoke_ass(srt_bytes="1\n00:00:00,000 --> 00:00:01,500\n今天这支口红真的很绝啊呀\n".encode("utf-8"), width=1080)
    assert "\\N" in ass
    dialogues = [line for line in ass.splitlines() if line.startswith("Dialogue:")]
    assert len(dialogues) == 2, dialogues
    for dialogue in dialogues:
        fields = dialogue.split(",", 3)
        cue_ms = _dialogue_ms(fields[2]) - _dialogue_ms(fields[1])
        assert abs(sum(_karaoke_centiseconds(dialogue)) * 10 - cue_ms) <= 10, dialogue


def test_karaoke_burns_via_ass_without_force_style(monkeypatch) -> None:
    """karaoke 必须走 .ass 文件且**不带** force_style（否则会盖掉逐字着色）。"""
    captured: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs):
        captured.append(command)
        Path(command[-1]).write_bytes(b"captioned")
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr("onetake_api.integrations.media.subtitle_burner.subprocess.run", fake_run)
    burn_subtitles(
        base_video_bytes=b"base",
        srt_bytes="1\n00:00:00,000 --> 00:00:02,000\n测试字幕\n".encode("utf-8"),
        duration_seconds=2, fps=25, width=1080, style="karaoke",
    )
    filter_graph = captured[0][captured[0].index("-vf") + 1]
    assert "subtitle.ass" in filter_graph
    assert "force_style" not in filter_graph


def test_karaoke_renders_progressive_highlight() -> None:
    """真渲染：已唱部分（白）随时间变多、未唱部分（浅灰）变少。"""
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        base = _black_video(root, width=1080, height=1920)
        video = burn_subtitles(
            base_video_bytes=base, srt_bytes="1\n00:00:00,000 --> 00:00:02,000\n今天这支口红\n".encode("utf-8"),
            duration_seconds=2, fps=25, width=1080, style="karaoke",
        )
        early = _frame(root, video, tag="karaoke-early", seconds=0.2).convert("RGB")
        late = _frame(root, video, tag="karaoke-late", seconds=1.85).convert("RGB")
    early_white = sum(1 for r, g, b in early.getdata() if r > 180 and g > 180 and b > 180)
    late_white = sum(1 for r, g, b in late.getdata() if r > 180 and g > 180 and b > 180)
    assert early_white < late_white, (early_white, late_white)


def test_karaoke_geometry_matches_standard() -> None:
    """karaoke 与 standard 的墨迹框必须一致（ASS 的脚本分辨率口径与 SRT 路径相同）。"""
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        base = _black_video(root, width=1080, height=1920)
        srt = "1\n00:00:00,000 --> 00:00:02,000\n测试字幕\n".encode("utf-8")
        standard = burn_subtitles(base_video_bytes=base, srt_bytes=srt, duration_seconds=2, fps=25, width=1080, style="standard")
        karaoke = burn_subtitles(base_video_bytes=base, srt_bytes=srt, duration_seconds=2, fps=25, width=1080, style="karaoke")
        box_standard = _ink_box(root, standard, tag="geom-standard")
        box_karaoke = _ink_box(root, karaoke, tag="geom-karaoke")
    # 两条路径的几何必须一致（允许 2px 的取整差：SRT 与 ASS 的渲染路径不同但口径相同）
    assert all(abs(first - second) <= 2 for first, second in zip(box_karaoke, box_standard)), (box_karaoke, box_standard)


def test_config_caption_style_keys_match_presets() -> None:
    """配置里的 Literal 取值必须与预设表一致（两处真相用一条测试钉住）。"""
    from typing import get_args

    from onetake_api.config import Settings

    annotation = Settings.model_fields["caption_style"].annotation
    assert set(get_args(annotation)) == set(CAPTION_STYLE_KEYS)


def test_bold_renders_more_ink_than_standard_and_minimal_renders_less() -> None:
    """验收 1：真渲染一遍 —— bold 的笔画覆盖率 > standard > minimal（不是只比字符串）。"""
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        base = _black_video(root, width=1080, height=1920)
        srt = "1\n00:00:00,000 --> 00:00:02,000\n测试字幕\n".encode("utf-8")
        ink = {
            style: _white_pixels(
                root,
                burn_subtitles(
                    base_video_bytes=base, srt_bytes=srt, duration_seconds=2, fps=25,
                    width=1080, style=style,
                ),
                tag=f"ink-{style}",
            )
            for style in ("standard", "bold", "minimal")
        }
    assert ink["bold"] > ink["standard"] > ink["minimal"]