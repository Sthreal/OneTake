from __future__ import annotations

import tempfile
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

from onetake_api.integrations.media.video_utils import (
    extract_head_frame,
    extract_tail_frame,
    resolve_segment_anchor,
)
from onetake_api.platform.errors import DomainError


class FrameExtractionError(DomainError):
    code = "VIDEO_FRAME_EXTRACTION_FAILED"
    http_status = 502
    retryable = True


class SegmentTailFrameExtractor:
    """从候选视频抽取尾部锚点帧（默认倒数第 2 帧），供下一段续写使用。"""

    def __init__(self, offset_frames: int = 2) -> None:
        self._offset_frames = max(0, int(offset_frames))

    def tail_frame(self, video_bytes: bytes) -> bytes:
        if not video_bytes:
            raise FrameExtractionError("候选视频为空，无法抽取尾帧")
        try:
            return extract_tail_frame(video_bytes, offset_frames=self._offset_frames)
        except DomainError as exc:
            raise FrameExtractionError(f"尾帧抽取失败：{exc.message}") from exc

    def head_frame(self, video_bytes: bytes) -> bytes:
        if not video_bytes:
            raise FrameExtractionError("候选视频为空，无法抽取首帧")
        try:
            return extract_head_frame(video_bytes)
        except DomainError as exc:
            raise FrameExtractionError(f"首帧抽取失败：{exc.message}") from exc


__all__ = [
    "FrameExtractionError",
    "SegmentTailFrameExtractor",
    "extract_head_frame",
    "extract_tail_frame",
    "resolve_segment_anchor",
]
