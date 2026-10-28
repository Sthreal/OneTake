from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

from onetake_api.platform.errors import DomainError

ANCHOR_SOURCE_SCENE_KEYFRAME = "scene_keyframe"
# 商品入画关键帧（Phase 1 起：已被用户采用的关键帧优先作为锚点）
ANCHOR_SOURCE_INTEGRATED_KEYFRAME = "integrated_keyframe"
ANCHOR_SOURCE_PREVIOUS_TAIL = "previous_tail"
ANCHOR_SOURCE_MANUAL = "manual"
ANCHOR_SOURCES = frozenset({ANCHOR_SOURCE_SCENE_KEYFRAME, ANCHOR_SOURCE_INTEGRATED_KEYFRAME, ANCHOR_SOURCE_PREVIOUS_TAIL, ANCHOR_SOURCE_MANUAL})
DEFAULT_TAIL_OFFSET_FRAMES = 2


class VideoProcessingError(DomainError):
    code = "VIDEO_PROCESSING_ERROR"
    http_status = 502
    retryable = True


class VideoContinuityError(DomainError):
    code = "PREVIOUS_SEGMENT_NOT_ACCEPTED"
    http_status = 409
    retryable = False


@dataclass(frozen=True)
class SegmentAnchor:
    frame_bytes: bytes
    source: str
    source_candidate_id: str | None = None
    # 尾帧（Phase 2 首尾帧转场）：与首帧一起交给 kf2v 模型，转场在片段内生成
    end_frame_bytes: bytes | None = None

    def __post_init__(self) -> None:
        if not self.frame_bytes:
            raise VideoProcessingError("分段锚点帧为空")
        if self.source not in ANCHOR_SOURCES:
            raise VideoProcessingError(f"未知锚点来源：{self.source}")


def _extract_frame_png(video_bytes: bytes, *, frame_index: int | None, offset_frames: int | None, label: str) -> bytes:
    if not video_bytes:
        raise VideoProcessingError("视频为空")
    if frame_index is not None and frame_index < 0:
        raise VideoProcessingError("帧索引必须是非负整数")
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        input_path = root / "clip.mp4"
        output_path = root / "frame.png"
        input_path.write_bytes(video_bytes)
        if frame_index is None:
            select_expr = f"reverse,select='eq(n\\,{max(0, int(offset_frames or 0))})',setpts=N/FRAME_RATE/TB"
        else:
            select_expr = f"select='eq(n\\,{frame_index})',setpts=N/FRAME_RATE/TB"
        command = [
            get_ffmpeg_exe(), "-y", "-i", str(input_path),
            "-vf", select_expr, "-vsync", "vfr", "-frames:v", "1", str(output_path),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except (subprocess.CalledProcessError, OSError) as exc:
            raise VideoProcessingError(f"{label}抽帧失败") from exc
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise VideoProcessingError(f"{label}抽帧结果为空")
        return output_path.read_bytes()


def extract_frame(video_bytes: bytes, *, frame_index: int) -> bytes:
    """按绝对帧号抽一帧，返回 PNG 字节。"""
    return _extract_frame_png(video_bytes, frame_index=frame_index, offset_frames=None, label="视频")


def extract_head_frame(video_bytes: bytes) -> bytes:
    return extract_frame(video_bytes, frame_index=0)


def extract_tail_frame(video_bytes: bytes, *, offset_frames: int = DEFAULT_TAIL_OFFSET_FRAMES) -> bytes:
    """抽取尾帧，返回 PNG 字节。offset_frames=0 取最后一帧，1 取倒数第二，以此类推。"""
    return _extract_frame_png(video_bytes, frame_index=None, offset_frames=offset_frames, label="视频尾")


def resolve_segment_anchor(
    segment_index: int,
    *,
    scene_keyframe: bytes | None = None,
    previous_tail_frame: bytes | None = None,
    previous_candidate_id: str | None = None,
    previous_accepted: bool = False,
    continuity_enabled: bool = True,
    override: bytes | None = None,
) -> SegmentAnchor:
    """决定一段视频的起手首帧。segment_index 是 0 基序号：<= 0 视为第一段（用分镜关键帧），

    其余按续段处理，默认用上一段已接受候选的尾帧。
    """
    if override:
        return SegmentAnchor(frame_bytes=override, source=ANCHOR_SOURCE_MANUAL)
    if segment_index <= 0:
        if not scene_keyframe:
            raise VideoProcessingError("第一段缺少分镜关键帧")
        return SegmentAnchor(frame_bytes=scene_keyframe, source=ANCHOR_SOURCE_SCENE_KEYFRAME)
    if not continuity_enabled:
        if not scene_keyframe:
            raise VideoProcessingError("续段缺少分镜关键帧")
        return SegmentAnchor(frame_bytes=scene_keyframe, source=ANCHOR_SOURCE_SCENE_KEYFRAME)
    if not previous_accepted:
        raise VideoContinuityError("上一段尚未接受候选，无法续写")
    if not previous_tail_frame:
        raise VideoContinuityError("上一段缺少尾帧锚点，无法续写")
    return SegmentAnchor(frame_bytes=previous_tail_frame, source=ANCHOR_SOURCE_PREVIOUS_TAIL, source_candidate_id=previous_candidate_id)


def concatenate_videos(
    *, clips: list[bytes], duration_seconds: float, fps: int, keep_audio: bool = False
) -> bytes:
    """拼接视频片段。

    `keep_audio=False`（默认）：**丢弃所有片段音轨**（`-an`）——这是产品契约所需：
    语音只来自 TTS 配音，用户可在成片前编辑字幕并重新配音，模型自带的声音无法跟随字幕变化。
    `keep_audio=True`：保留模型原声（整片一次生成路径的口型台词场景）；缺音轨的片段会自动补静音，
    避免 concat 因流不一致而失败。
    """
    if not clips:
        raise VideoProcessingError("没有可拼接的视频片段")
    if keep_audio:
        clips = [_ensure_audio_track(clip) for clip in clips]
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
            command = [
                get_ffmpeg_exe(), "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
                "-t", f"{duration_seconds:.3f}", "-r", str(fps),
                "-c:v", "libx264", "-b:v", "8M", "-pix_fmt", "yuv420p",
            ]
            command += ["-c:a", "aac", "-ar", "48000", "-ac", "2"] if keep_audio else ["-an"]
            command.append(str(output))
            subprocess.run(command, check=True, capture_output=True, text=True)
        except (subprocess.CalledProcessError, OSError) as exc:
            raise VideoProcessingError("视频片段拼接失败") from exc
        return output.read_bytes()




def inspect_has_audio(video_bytes: bytes) -> bool:
    """视频是否含音轨（拼接时决定是否需要补静音、以及校验语音开关）。"""
    if not video_bytes:
        return False
    with tempfile.TemporaryDirectory() as temp_dir:
        input_path = Path(temp_dir) / "probe.mp4"
        input_path.write_bytes(video_bytes)
        try:
            completed = subprocess.run(
                [get_ffmpeg_exe(), "-hide_banner", "-i", str(input_path), "-f", "null", "-"],
                check=False, capture_output=True, text=True,
            )
        except OSError:
            return False
        return any(" Audio: " in line for line in completed.stderr.splitlines())


def _ensure_audio_track(video_bytes: bytes) -> bytes:
    """给没有音轨的片段补一条静音轨，保证 concat 时所有输入流一致。"""
    if inspect_has_audio(video_bytes):
        return video_bytes
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        input_path = root / "in.mp4"
        output_path = root / "out.mp4"
        input_path.write_bytes(video_bytes)
        subprocess.run(
            [
                get_ffmpeg_exe(), "-y", "-i", str(input_path),
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                "-shortest", "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "copy", "-c:a", "aac", "-ar", "48000", "-ac", "2", str(output_path),
            ],
            check=True, capture_output=True, text=True,
        )
        return output_path.read_bytes()


def inspect_video_dimensions(video_bytes: bytes) -> tuple[int, int]:
    if not video_bytes:
        raise VideoProcessingError("视频为空")
    with tempfile.TemporaryDirectory() as temp_dir:
        input_path = Path(temp_dir) / "video.mp4"
        input_path.write_bytes(video_bytes)
        try:
            completed = subprocess.run(
                [get_ffmpeg_exe(), "-hide_banner", "-i", str(input_path), "-f", "null", "-"],
                check=True,
                capture_output=True,
                text=True,
            )
        except (subprocess.CalledProcessError, OSError) as exc:
            raise VideoProcessingError("视频元数据读取失败") from exc
        video_line = next((line for line in completed.stderr.splitlines() if " Video: " in line), None)
        size_match = re.search(r"(\d{2,5})x(\d{2,5})", video_line or "")
        if size_match is None:
            raise VideoProcessingError("视频分辨率缺失")
        return int(size_match.group(1)), int(size_match.group(2))


def inspect_video_duration(video_bytes: bytes) -> float:
    """返回视频时长（秒）。"""
    if not video_bytes:
        raise VideoProcessingError("视频为空")
    with tempfile.TemporaryDirectory() as temp_dir:
        input_path = Path(temp_dir) / "video.mp4"
        input_path.write_bytes(video_bytes)
        try:
            completed = subprocess.run(
                [get_ffmpeg_exe(), "-hide_banner", "-i", str(input_path), "-f", "null", "-"],
                check=True, capture_output=True, text=True,
            )
        except (subprocess.CalledProcessError, OSError) as exc:
            raise VideoProcessingError("视频时长读取失败") from exc
        match = re.search(r"Duration: (\d+):(\d{2}):(\d{2}\.\d+)", completed.stderr)
        if match is None:
            raise VideoProcessingError("视频时长缺失")
        hours, minutes, seconds = match.groups()
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
