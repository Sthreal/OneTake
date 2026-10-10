from __future__ import annotations

import io

import pytest
from PIL import Image

from onetake_api.integrations.media.video_utils import (
    ANCHOR_SOURCE_MANUAL,
    ANCHOR_SOURCE_PREVIOUS_TAIL,
    ANCHOR_SOURCE_SCENE_KEYFRAME,
    VideoContinuityError,
    VideoProcessingError,
    extract_frame,
    extract_head_frame,
    extract_tail_frame,
    resolve_segment_anchor,
)
from onetake_api.integrations.mock_video.renderer import render_base_video


def _video(*, frames: int = 24, fps: int = 24) -> bytes:
    source = io.BytesIO()
    Image.new("RGB", (360, 640), (10, 120, 200)).save(source, format="PNG")
    return render_base_video(
        image_bytes=source.getvalue(),
        mode="product",
        template_id="clean",
        duration_seconds=frames / fps,
        width=360,
        height=640,
        fps=fps,
    )


def _size(frame: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(frame)) as image:
        assert image.format == "PNG"
        assert image.mode == "RGB"
        return image.size


def test_extract_head_frame_returns_first_frame() -> None:
    frame = extract_head_frame(_video())
    assert _size(frame) == (360, 640)


def test_extract_tail_frame_offset_selects_frame_from_end() -> None:
    video = _video()
    last = extract_tail_frame(video, offset_frames=0)
    second_last = extract_tail_frame(video, offset_frames=1)
    default_tail = extract_tail_frame(video)
    assert _size(last) == (360, 640)
    assert _size(second_last) == (360, 640)
    assert _size(default_tail) == (360, 640)


def test_extract_frame_by_index_is_bounded() -> None:
    video = _video(frames=24)
    assert _size(extract_frame(video, frame_index=0)) == (360, 640)
    assert _size(extract_frame(video, frame_index=23)) == (360, 640)


def test_extract_frame_rejects_negative_index() -> None:
    with pytest.raises(VideoProcessingError, match="帧索引"):
        extract_frame(_video(), frame_index=-1)


def test_extract_frame_rejects_empty_video() -> None:
    with pytest.raises(VideoProcessingError, match="视频为空"):
        extract_tail_frame(b"")


def test_resolve_anchor_first_segment_uses_scene_keyframe() -> None:
    anchor = resolve_segment_anchor(0, scene_keyframe=b"keyframe")
    assert anchor.source == ANCHOR_SOURCE_SCENE_KEYFRAME
    assert anchor.frame_bytes == b"keyframe"


def test_resolve_anchor_first_segment_requires_keyframe() -> None:
    with pytest.raises(VideoProcessingError, match="分镜关键帧"):
        resolve_segment_anchor(0)


def test_resolve_anchor_continuation_uses_previous_tail() -> None:
    anchor = resolve_segment_anchor(
        1,
        scene_keyframe=b"keyframe",
        previous_tail_frame=b"tail",
        previous_candidate_id="c-1",
        previous_accepted=True,
    )
    assert anchor.source == ANCHOR_SOURCE_PREVIOUS_TAIL
    assert anchor.frame_bytes == b"tail"
    assert anchor.source_candidate_id == "c-1"


def test_resolve_anchor_continuation_without_acceptance_raises() -> None:
    with pytest.raises(VideoContinuityError) as excinfo:
        resolve_segment_anchor(1, scene_keyframe=b"keyframe", previous_accepted=False)
    assert excinfo.value.code == "PREVIOUS_SEGMENT_NOT_ACCEPTED"


def test_resolve_anchor_continuation_without_tail_raises() -> None:
    with pytest.raises(VideoContinuityError, match="尾帧锚点"):
        resolve_segment_anchor(1, previous_accepted=True, previous_tail_frame=None)


def test_resolve_anchor_continuity_disabled_falls_back_to_keyframe() -> None:
    anchor = resolve_segment_anchor(2, scene_keyframe=b"keyframe", continuity_enabled=False)
    assert anchor.source == ANCHOR_SOURCE_SCENE_KEYFRAME
    assert anchor.frame_bytes == b"keyframe"


def test_resolve_anchor_manual_override_wins() -> None:
    anchor = resolve_segment_anchor(
        3,
        scene_keyframe=b"keyframe",
        previous_tail_frame=b"tail",
        previous_accepted=True,
        override=b"manual",
    )
    assert anchor.source == ANCHOR_SOURCE_MANUAL
    assert anchor.frame_bytes == b"manual"
