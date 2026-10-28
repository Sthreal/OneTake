"""抽帧拼图（contact sheet）：自动检查看不出"字幕碰撞、构图难看、转场跳变"，
所以把**真实拼接点**附近的帧抽出来拼成一张图，让人一眼看完再决定是否交付。

拼接点是断帧高发区，因此每段边界抽两帧（边界前 0.2s / 边界后 0.2s），并用红框标出。
"""
from __future__ import annotations

import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe
from PIL import Image, ImageDraw

from onetake_api.platform.errors import DomainError

DEFAULT_COLUMNS = 3
DEFAULT_THUMB_WIDTH = 360
SPLICE_EPSILON = 0.2


class ContactSheetError(DomainError):
    code = "CONTACT_SHEET_FAILED"
    http_status = 502
    retryable = True


def splice_timestamps(boundaries: list[float], *, duration_seconds: float) -> list[float]:
    """把分段边界转成抽帧时刻：每个边界前后各取一帧，并保证至少覆盖首尾。"""
    stamps: list[float] = [0.0, max(0.0, duration_seconds - 0.1)]
    for boundary in boundaries:
        before = max(0.0, boundary - SPLICE_EPSILON)
        after = min(max(0.0, duration_seconds - 0.01), boundary + SPLICE_EPSILON)
        stamps.extend([before, after])
    unique: list[float] = []
    for stamp in sorted(stamps):
        if stamp < 0:
            continue
        if not unique or abs(stamp - unique[-1]) > 0.05:
            unique.append(round(stamp, 3))
    return unique


def build_contact_sheet(
    video_bytes: bytes,
    *,
    timestamps: list[float],
    columns: int = DEFAULT_COLUMNS,
    thumb_width: int = DEFAULT_THUMB_WIDTH,
    highlight: bool = True,
) -> bytes:
    if not video_bytes:
        raise ContactSheetError("抽帧拼图输入为空")
    if not timestamps:
        raise ContactSheetError("抽帧拼图缺少时间点")
    frames: list[tuple[float, Image.Image]] = []
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        video_path = root / "input.mp4"
        video_path.write_bytes(video_bytes)
        for index, stamp in enumerate(timestamps):
            frame_path = root / f"frame-{index}.png"
            command = [
                get_ffmpeg_exe(), "-y", "-ss", f"{max(0.0, stamp):.3f}", "-i", str(video_path),
                "-frames:v", "1", str(frame_path),
            ]
            try:
                subprocess.run(command, check=True, capture_output=True, errors="replace")
            except (subprocess.CalledProcessError, OSError) as exc:
                raise ContactSheetError(f"第 {index + 1} 张抽帧失败") from exc
            if not frame_path.is_file() or frame_path.stat().st_size == 0:
                raise ContactSheetError(f"第 {index + 1} 张抽帧为空")
            with Image.open(frame_path) as image:
                frame = image.convert("RGB")
                ratio = thumb_width / max(1, frame.width)
                frame = frame.resize((thumb_width, max(1, int(frame.height * ratio))), Image.LANCZOS)
                frames.append((stamp, frame.copy()))
    return _tile(frames, columns=columns, highlight=highlight)


def _tile(frames: list[tuple[float, Image.Image]], *, columns: int, highlight: bool) -> bytes:
    columns = max(1, min(columns, len(frames)))
    rows = (len(frames) + columns - 1) // columns
    thumb_width, thumb_height = frames[0][1].size
    padding = 8
    label_height = 26
    cell_width = thumb_width + padding * 2
    cell_height = thumb_height + padding * 2 + label_height
    sheet = Image.new("RGB", (cell_width * columns, cell_height * rows), (24, 24, 28))
    draw = ImageDraw.Draw(sheet)
    for index, (stamp, frame) in enumerate(frames):
        row, column = divmod(index, columns)
        left = column * cell_width + padding
        top = row * cell_height + padding
        sheet.paste(frame, (left, top))
        if highlight:
            draw.rectangle((left - 2, top - 2, left + thumb_width + 1, top + thumb_height + 1), outline=(255, 64, 64), width=2)
        draw.text((left, top + thumb_height + 6), f"{stamp:.2f}s", fill=(220, 220, 220))
    output = BytesIO()
    sheet.save(output, format="PNG", optimize=True)
    return output.getvalue()