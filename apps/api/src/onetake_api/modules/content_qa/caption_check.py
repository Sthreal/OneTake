"""字幕安全区检查（批次 1b）。

单靠抽帧很难判"字幕被裁切"，所以分**两层**：

1. **渲染前估算**：按**实际会被渲染的行**（`split_srt_bytes` → `parse_srt_bytes`）用 PIL 量字宽，
   算出每句字幕的墨迹框，检查 ① 单行是否宽过水平安全区 ② 字幕带顶是否过高 ③ 是否与 AIGC 标识框重叠；
2. **渲染后探针**：抽帧检出"字幕样"像素（近白 + 紧邻深色描边），检查是否贴底 / 越左右边 / 带高异常 / **根本没出现**。

接入：交付门的一条 `caption_safety`（**warn，不阻断**），与 `contact_sheet` 同思路。

几何真源：字号/描边来自 `caption_styles`，边距来自 `subtitle_burner`，标识框直接取
`aigc_label_png.build_label_overlay_png()` 的 alpha 包围盒（**与生产同一份几何**，不复制常量）。

⚠️ 实测标定（1080×1920、Noto Sans SC，证据见本切片记录）：
- **水平**安全区 = `width × (1 − 2×MarginL/384)`（libass 的脚本宽度恒为 384）→ 1080 宽 = **630px**；
  实测 8 个汉字（584px）单行、9 个（≈657px）自动折行，与该式**一致**；
- **字墨**：单行墨高 ≈ 0.93 em、每个汉字墨宽 ≈ 1.0 em、**行距** = `FontSize × height/288`；
  其中 `em ≈ FontSize × height/288 × 0.684`（libass 会按字体自身 ascent/descent 归一化字号）；
- **底部**：字墨底边距帧底 ≈ `MarginV × height/288 + 0.2 em`（实测 415px @ MarginV=60）；
- **已知不确定**：换帧尺寸后 libass 的归一化系数实测**不稳定**（720×1280 明显偏小），所以估算按
  **生产帧 1080×1920 标定**，只用于**粗筛**；最终判据以**渲染后探针**为准。

⚠️ 另有一条如实边界：本仓切分口径（单条 ≤11 字、每行 ≤6 字）已经把单行压到安全区以内，
所以"单行超宽"在**现有产品路径上不会发生** —— 这一层守的是"改样式 / 改帧尺寸 / 改切分口径"之后的情况。
"""
from __future__ import annotations

import io
import subprocess
from math import ceil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageFilter, ImageFont
from imageio_ffmpeg import get_ffmpeg_exe

from onetake_api.integrations.media.aigc_label_png import build_label_overlay_png
from onetake_api.integrations.media.caption_styles import font_size_for, resolve_caption_style
# 边距/字体用**模块引用**读取（`subtitle_burner` 是单一真源）：这样测试或配置改边距时
# 估算与渲染会一起变，不会出现"估算用旧值、渲染用新值"的错位。
from onetake_api.integrations.media import subtitle_burner as burner
from onetake_api.integrations.media.subtitle_segmentation import parse_srt_bytes, split_srt_bytes

# ---- libass 几何常数（全部实测标定，见模块 docstring）----
PLAY_RES_X = 384
PLAY_RES_Y = 288
GLYPH_SCALE = 0.684
INK_HEIGHT_RATIO = 0.93
BASELINE_PAD_RATIO = 0.20
SAFE_TOP_RATIO = 0.62
LABEL_GAP_PX = 6
# ---- 渲染后探针 ----
BRIGHT_THRESHOLD = 235
OUTLINE_THRESHOLD = 60
MIN_CAPTION_PIXELS = 50
BAND_REGION_RATIO = 0.55
MAX_BAND_HEIGHT_RATIO = 0.35
FRAME_SAMPLES = (0.15, 0.5, 0.85)
EDGE_TOLERANCE_PX = 3

SEVERITY_INFO = "info"
SEVERITY_WARN = "warn"

KIND_WIDE_LINE = "wide_line"
KIND_TALL_BAND = "tall_band"
KIND_LABEL_OVERLAP = "label_overlap"
KIND_CAPTION_MISSING = "caption_missing"
KIND_PINNED_BOTTOM = "pinned_bottom"
KIND_EDGE_TOUCH = "edge_touch"
KIND_BAND_TOO_TALL = "band_too_tall"


@dataclass(frozen=True)
class CueBox:
    index: int
    start_seconds: float
    end_seconds: float
    text: str
    line_count: int
    width_px: float
    height_px: float
    box: tuple[int, int, int, int]        # x0, y0, x1, y1（墨迹框）


@dataclass(frozen=True)
class CaptionFinding:
    kind: str
    message: str
    at_seconds: list[float] = field(default_factory=list)
    # info = 渲染器会自行处理（如自动折行），不阻断也不要求人确认；warn = 需要人看一眼
    severity: str = SEVERITY_WARN


def glyph_em_px(*, height: int, font_size_units: int) -> float:
    return font_size_units * height / PLAY_RES_Y * GLYPH_SCALE


def safe_width_px(width: int, *, margin_l: int | None = None, margin_r: int | None = None) -> float:
    """水平安全区：libass 的脚本宽度恒为 384，左右边距按 `width/384` 换算。"""
    left = burner.CAPTION_MARGIN_L if margin_l is None else margin_l
    right = burner.CAPTION_MARGIN_R if margin_r is None else margin_r
    return width * (1 - (left + right) / PLAY_RES_X)


def label_box(
    *, width: int, height: int, position: str, size_ratio: float, margin_ratio: float, avoid_subtitle: bool
) -> tuple[int, int, int, int] | None:
    """AIGC 标识框：直接用生产那一份位图叠加的 alpha 包围盒（不复制几何）。"""
    from onetake_api.integrations.media.aigc_label import resolve_position

    resolved = resolve_position(position=position, avoid_subtitle=avoid_subtitle)
    for text in ("AI生成", "AI内容"):
        try:
            png = build_label_overlay_png(
                text=text, width=width, height=height, position=resolved,
                size_ratio=size_ratio, margin_ratio=margin_ratio,
            )
        except ValueError:
            continue
        with Image.open(io.BytesIO(png)) as image:
            box = image.convert("RGBA").getchannel("A").getbbox()
        if box:
            return box
    return None


def estimate_cue_boxes(
    *, cues: list[tuple[str, float, float]], width: int, height: int, font_size_units: int,
    margin_v_units: int | None = None,
) -> list[CueBox]:
    """按渲染口径估算每句的墨迹框。`cues` = [(会被渲染的文本, 起, 止)]。"""
    em = glyph_em_px(height=height, font_size_units=font_size_units)
    if em <= 0 or not cues:
        return []
    # 默认值在**调用时**才取（而不是 def 时绑定），这样测试与配置改边距都能生效
    margin_v = burner.CAPTION_MARGIN_V if margin_v_units is None else margin_v_units
    font = ImageFont.truetype(str(burner.CAPTION_FONT_PATH), size=max(1, round(em)))
    line_step = font_size_units * height / PLAY_RES_Y
    baseline = height - (margin_v * height / PLAY_RES_Y + BASELINE_PAD_RATIO * em)
    boxes: list[CueBox] = []
    safe_width = safe_width_px(width)
    for index, (text, start, end) in enumerate(cues):
        parts = [part for part in text.split("\n") if part] or [""]
        widths = [font.getlength(part) for part in parts]
        width_px = max(widths) if widths else 0.0
        # 超宽的行**渲染器会自己折**（实测：1080 宽下 9 个汉字起就折）→ 按折行后的行数算带高
        visual_lines = sum(max(1, ceil(part_width / safe_width)) for part_width in widths) if widths else 1
        height_px = INK_HEIGHT_RATIO * em + (visual_lines - 1) * line_step
        x0 = round(width / 2 - width_px / 2)
        x1 = round(width / 2 + width_px / 2)
        y1 = round(baseline)
        y0 = round(baseline - height_px)
        boxes.append(CueBox(
            index=index + 1, start_seconds=start, end_seconds=end, text=text, line_count=visual_lines,
            width_px=width_px, height_px=height_px, box=(x0, y0, x1, y1),
        ))
    return boxes


def srt_cues(srt_bytes: bytes) -> list[tuple[str, float, float]]:
    """取出**实际会被渲染**的行（先走生产同一条切分，再解析），带上每句时间。"""
    expanded = parse_srt_bytes(split_srt_bytes(srt_bytes))
    return [(cue.text, cue.start_ms / 1000, cue.end_ms / 1000) for cue in expanded]


def check_caption_layout(
    *,
    width: int,
    height: int,
    style: str | None = None,
    srt_bytes: bytes | None = None,
    authored_lines: list[str] | None = None,
    label_position: str = "top_right",
    label_size_ratio: float = 0.028,
    label_margin_ratio: float = 0.04,
    avoid_subtitle: bool = True,
) -> list[CaptionFinding]:
    """渲染前估算（纯函数，零成本）。

    `srt_bytes` 走生产切分口径；`authored_lines` 允许**绕过切分**直接给行（预检 / 单测用）。
    """
    if authored_lines is not None:
        cues = [(line, 0.0, 0.0) for line in authored_lines]
    elif srt_bytes:
        cues = srt_cues(srt_bytes)
    else:
        return []
    preset = resolve_caption_style(style)
    font_size_units = font_size_for(width, preset)
    boxes = estimate_cue_boxes(cues=cues, width=width, height=height, font_size_units=font_size_units)
    safe_width = safe_width_px(width)
    marker = label_box(
        width=width, height=height, position=label_position,
        size_ratio=label_size_ratio, margin_ratio=label_margin_ratio, avoid_subtitle=avoid_subtitle,
    )
    findings: list[CaptionFinding] = []
    for cue in boxes:
        at = [cue.start_seconds] if cue.end_seconds > cue.start_seconds else []
        if cue.width_px > safe_width:
            # 只记为 info：实测渲染器会自动折行（9 个汉字起就会折），画面不裁不越，属"观感与预期不同"而非缺陷
            findings.append(CaptionFinding(
                KIND_WIDE_LINE,
                f"字幕第 {cue.index} 句单行宽约 {cue.width_px:.0f}px，超过水平安全区 {safe_width:.0f}px：渲染器会自动折成多行（无裁切风险）",
                at, SEVERITY_INFO,
            ))
        if cue.box[1] < height * SAFE_TOP_RATIO:
            findings.append(CaptionFinding(
                KIND_TALL_BAND,
                f"字幕第 {cue.index} 句带顶在 y={cue.box[1]}，已高于帧高 {SAFE_TOP_RATIO:.0%} 线（{height * SAFE_TOP_RATIO:.0f}px）：字幕占了过多画面",
                at,
            ))
        if marker and _intersects(cue.box, marker, gap=LABEL_GAP_PX):
            findings.append(CaptionFinding(
                KIND_LABEL_OVERLAP,
                f"字幕第 {cue.index} 句与 AIGC 标识框 {marker} 重叠（间距不足 {LABEL_GAP_PX}px）",
                at,
            ))
    return findings


def probe_caption_pixels(*, video_bytes: bytes, width: int, height: int) -> list[CaptionFinding]:
    """渲染后探针：抽帧找"字幕样"像素，判贴底 / 越边 / 带高异常 / 缺失。"""
    if not video_bytes:
        return []
    boxes: list[tuple[int, int, int, int]] = []
    sampled: list[float] = []
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source = root / "input.mp4"
        source.write_bytes(video_bytes)
        duration = _probe_seconds(video_bytes)
        for index, ratio in enumerate(FRAME_SAMPLES, start=1):
            seconds = round(duration * ratio, 2)
            frame_path = root / f"frame-{index}.png"
            try:
                subprocess.run(
                    [get_ffmpeg_exe(), "-y", "-ss", f"{seconds:.3f}", "-i", str(source),
                     "-frames:v", "1", str(frame_path)],
                    check=True, capture_output=True, text=True,
                )
            except (subprocess.CalledProcessError, OSError):
                continue
            with Image.open(frame_path) as image:
                mask_box, count = _caption_pixels(image.convert("RGB"))
            sampled.append(seconds)
            if mask_box and count >= MIN_CAPTION_PIXELS:
                boxes.append(mask_box)
    if not boxes:
        return [CaptionFinding(
            KIND_CAPTION_MISSING,
            "抽帧未在画面下部检出字幕像素：字幕可能没烧上去（或样式被改到看不出）",
            sampled,
        )]
    x0 = min(box[0] for box in boxes)
    y0 = min(box[1] for box in boxes)
    x1 = max(box[2] for box in boxes)
    y1 = max(box[3] for box in boxes)
    findings: list[CaptionFinding] = []
    if y1 >= height - EDGE_TOLERANCE_PX:
        findings.append(CaptionFinding(
            KIND_PINNED_BOTTOM,
            f"字幕像素贴到画面底部（y1={y1} / 帧高 {height}）：疑似被裁切或边距失效",
            sampled,
        ))
    if x0 <= EDGE_TOLERANCE_PX or x1 >= width - EDGE_TOLERANCE_PX:
        findings.append(CaptionFinding(
            KIND_EDGE_TOUCH,
            f"字幕像素贴到左右边（x0={x0}, x1={x1} / 帧宽 {width}）：疑似越出安全区",
            sampled,
        ))
    if (y1 - y0) > height * MAX_BAND_HEIGHT_RATIO:
        findings.append(CaptionFinding(
            KIND_BAND_TOO_TALL,
            f"字幕带高 {y1 - y0}px 超过帧高 {MAX_BAND_HEIGHT_RATIO:.0%}（{height * MAX_BAND_HEIGHT_RATIO:.0f}px）：疑似折行过多",
            sampled,
        ))
    return findings


def check_captions(
    *,
    width: int,
    height: int,
    srt_bytes: bytes | None = None,
    video_bytes: bytes | None = None,
    style: str | None = None,
    label_position: str = "top_right",
    label_size_ratio: float = 0.028,
    label_margin_ratio: float = 0.04,
    avoid_subtitle: bool = True,
) -> list[CaptionFinding]:
    """交付门用入口：两层合并（有字幕就查布局；有视频就探针）。v1 只查视频层。"""
    findings: list[CaptionFinding] = []
    if srt_bytes:
        findings.extend(check_caption_layout(
            width=width, height=height, style=style, srt_bytes=srt_bytes,
            label_position=label_position, label_size_ratio=label_size_ratio,
            label_margin_ratio=label_margin_ratio, avoid_subtitle=avoid_subtitle,
        ))
    if video_bytes:
        findings.extend(probe_caption_pixels(video_bytes=video_bytes, width=width, height=height))
    return findings


# ---- 内部工具 ----


def _caption_pixels(image: Image.Image) -> tuple[tuple[int, int, int, int] | None, int]:
    """"字幕样"像素 = 近白且 5px 邻域内存在深色（描边）。只看画面下部区域。"""
    height = image.height
    top = int(height * (1 - BAND_REGION_RATIO))
    region = image.crop((0, top, image.width, height))
    gray = region.convert("L")
    bright = gray.point(lambda value: 255 if value >= BRIGHT_THRESHOLD else 0)
    outline = gray.filter(ImageFilter.MinFilter(5)).point(lambda value: 255 if value <= OUTLINE_THRESHOLD else 0)
    mask = _and_masks(bright, outline)
    box = mask.getbbox()
    if box is None:
        return None, 0
    count = sum(1 for value in mask.getdata() if value)
    return (box[0], box[1] + top, box[2], box[3] + top), count


def _and_masks(first: Image.Image, second: Image.Image) -> Image.Image:
    return Image.frombytes("L", first.size, bytes(a & b for a, b in zip(first.tobytes(), second.tobytes())))


def _intersects(
    first: tuple[int, int, int, int], second: tuple[int, int, int, int], *, gap: int
) -> bool:
    return not (
        first[2] + gap < second[0] or second[2] + gap < first[0]
        or first[3] + gap < second[1] or second[3] + gap < first[1]
    )


def _probe_seconds(video_bytes: bytes) -> float:
    from onetake_api.integrations.media.video_utils import inspect_video_duration

    try:
        return max(0.1, inspect_video_duration(video_bytes))
    except Exception:  # noqa: BLE001 - 探测失败时退化成"按 2 秒采样"，不因探针本身把交付门搞挂
        return 2.0
