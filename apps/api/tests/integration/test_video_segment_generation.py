from __future__ import annotations

import io
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image
from sqlalchemy.orm import Session

from onetake_api.integrations.mock_video.renderer import render_base_video
from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.modules.content_plan.domain import STATUS_CONFIRMED, ContentPlan, ContentScene, ContentVariant
from onetake_api.modules.content_plan.repository import ContentPlanRepository
from onetake_api.modules.main_image.domain import MainImageVersion
from onetake_api.modules.main_image.repository import MainImageRepository
from onetake_api.modules.pipeline.public import PipelinePublicService
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.modules.subtitle.domain import SUBTITLE_CONFIRMED, SubtitleVersion
from onetake_api.modules.subtitle.repository import SubtitleRepository
from onetake_api.modules.video_plan.segment_frame import SegmentTailFrameExtractor
from onetake_api.modules.video_plan.segment_generation import SegmentVideoGenerator
from onetake_api.modules.video_plan.service import VideoPlanApplicationService
from onetake_api.modules.voice.domain import VOICE_CONFIRMED, VoiceRun
from onetake_api.modules.voice.repository import VoiceRepository
from imageio_ffmpeg import get_ffmpeg_exe

WIDTH, HEIGHT = 360, 640


@dataclass
class _Generated:
    video_bytes: bytes
    provider_name: str = "wan-i2v"


class FakeWanI2V:
    """把传入的锚点图直接渲染成短视频，用于验证续段确实使用了上一段的尾帧。"""

    def __init__(self, recorder: list[bytes], *, width: int, height: int) -> None:
        self._recorder = recorder
        self._width = width
        self._height = height
        self.provider_name = "wan-i2v"

    def generate(self, *, image_bytes: bytes, prompt: str, duration_seconds: int, negative_prompt: str | None = None):
        self._recorder.append(image_bytes)
        video = render_base_video(
            image_bytes=image_bytes, mode="product", template_id="clean",
            duration_seconds=1.0, width=self._width, height=self._height, fps=24,
        )
        return video, "task"


def _raw_rgb(png_bytes: bytes) -> bytes:
    with tempfile.TemporaryDirectory() as temp_dir:
        png = Path(temp_dir) / "f.png"
        raw = Path(temp_dir) / "f.rgb"
        png.write_bytes(png_bytes)
        subprocess.run([get_ffmpeg_exe(), "-y", "-i", str(png), "-f", "rawvideo", "-pix_fmt", "rgb24", str(raw)], check=True, capture_output=True)
        return raw.read_bytes()


def _make_scene(order: int, *, start_seconds: float | None = None) -> ContentScene:
    start = float(order * 5) if start_seconds is None else start_seconds
    return ContentScene(
        scene_id=f"scene_{order}", order=order, purpose="展示", script_excerpt="文案",
        start_seconds=start, end_seconds=start + 5, shot_type="medium", prompt="商品展示",
        overlay_product=True, product_position="center", background_style="clean", template_id="clean",
        subtitle_segment_ids=[order + 1], qa_rules=[], visual_goal="product_reveal", subject_action="缓慢展示商品",
        camera_move="slow_push_in", product_mode="overlay", transition="fade",
    )


def _seed_plan(session: Session, storage: ObjectStoragePublicService, product_name: str, *, order_base: int = 0):
    project = ProjectPublicService().create_project(session, product_name=product_name, product_note=None)
    now = datetime.now(UTC)
    main_key = f"projects/{project.id}/main.png"
    source = io.BytesIO()
    Image.new("RGB", (WIDTH, HEIGHT), (200, 60, 60)).save(source, format="PNG")
    storage.put_bytes(object_key=main_key, content=source.getvalue(), mime_type="image/png")
    MainImageRepository().add(session, MainImageVersion("miv_gen", project.id, "ast_gen", "confirmed", "edt_gen", "mat_gen", main_key, None, 2000, 2000, 1000, 1000, 1000, 0.9, None, now, now, now, now))
    VoiceRepository().add(session, VoiceRun("voi_gen", project.id, "scr_gen", VOICE_CONFIRMED, True, True, "mock", "cosyvoice-v2", "female", "zh", 1.0, "测试。", f"projects/{project.id}/v.wav", "audio/wav", 15.0, [], None, now, now, now, now))
    SubtitleRepository().add(session, SubtitleVersion("sub_gen", project.id, "scr_gen", "voi_gen", SUBTITLE_CONFIRMED, True, "zh", [{"index": 1, "text": "测试。", "start": 0, "end": 15}], f"projects/{project.id}/s.srt", None, now, now, now, now))
    PipelinePublicService().mark_audio_subtitle_confirmed(session, project.id)
    content_plan = ContentPlan(
        id="cpl_gen", project_id=project.id, script_version_id="scr_gen", subtitle_version_id="sub_gen",
        status=STATUS_CONFIRMED, provider="rules", model="rules-v1",
        variants=[
            ContentVariant(
                "var_gen", "标准", "clean",
                [_make_scene(order_base + index, start_seconds=float(index * 5)) for index in range(3)],
            )
        ],
        selected_variant_index=0, total_duration_seconds=15.0, error_code=None, created_at=now, updated_at=now, confirmed_at=now,
    )
    ContentPlanRepository().add(session, content_plan)
    plan = VideoPlanApplicationService(storage=storage).create_plan(
        session, project_id=project.id, mode="product", template_id="clean"
    ).plan
    session.flush()
    return project.id, plan


def _service(storage, recorder):
    generator = SegmentVideoGenerator(
        storage=storage,
        adapter_factory=lambda plan: FakeWanI2V(recorder, width=plan.width, height=plan.height),
        frame_runner=SegmentTailFrameExtractor(offset_frames=2),
    )
    from onetake_api.modules.video_plan.segment_service import VideoSegmentApplicationService
    return VideoSegmentApplicationService(storage=storage, generator=generator)


def test_continuation_uses_previous_accepted_tail_frame(
    db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    monkeypatch.setenv("MOCK_PROVIDERS", "true")
    monkeypatch.setenv("PRODUCT_SCENE_ENABLED", "true")
    monkeypatch.setenv("VIDEO_CONTINUITY_ENABLED", "true")
    from onetake_api.config import get_settings
    get_settings.cache_clear()

    recorder: list[bytes] = []
    project_id, plan = _seed_plan(db_session, object_storage, "分段续写")
    service = _service(object_storage, recorder)

    segments = service.materialize_segments(db_session, project_id=project_id)
    assert [seg.order_index for seg in segments] == [0, 1, 2]

    first = service.generate_candidate(db_session, project_id=project_id, segment_id=segments[0].id, seed=11)
    first_segment = next(seg for seg in first if seg.order_index == 0)
    assert first_segment.status == "awaiting_review"
    first_candidate = first_segment.candidates[-1]
    assert first_candidate.anchor_source == "scene_keyframe"
    service.accept_candidate(db_session, project_id=project_id, candidate_id=first_candidate.id)

    accepted_tail_png = b"".join(object_storage.read_object(object_key=first_candidate.tail_frame_object_key))
    second = service.generate_candidate(db_session, project_id=project_id, segment_id=segments[1].id, seed=22)
    second_segment = next(seg for seg in second if seg.order_index == 1)
    second_candidate = second_segment.candidates[-1]
    assert second_candidate.anchor_source == "previous_tail"
    assert second_candidate.anchor_candidate_id == first_candidate.id

    # 第二次生成收到的锚点图必须与第一段尾帧像素一致
    assert len(recorder) == 2
    assert _raw_rgb(recorder[1]) == _raw_rgb(accepted_tail_png)
    assert second_candidate.video_object_key and second_candidate.tail_frame_object_key and second_candidate.head_frame_object_key

def test_first_segment_uses_scene_keyframe_with_one_based_scene_order(
    db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    """回归：真实内容方案的 scene.order 是 1 基。

    content_plan/generator.py 写的是 order=index + 1，而 resolve_segment_anchor 用
    segment_index <= 0 表示第一段（0 基约定）。修复前调用方直接传 order_index，
    第 1 段会被判成续段并抛 PREVIOUS_SEGMENT_NOT_ACCEPTED，整条段级生产线在真实数据上跑不通。
    """
    monkeypatch.setenv("MOCK_PROVIDERS", "true")
    monkeypatch.setenv("PRODUCT_SCENE_ENABLED", "true")
    monkeypatch.setenv("VIDEO_CONTINUITY_ENABLED", "true")
    from onetake_api.config import get_settings
    get_settings.cache_clear()

    recorder: list[bytes] = []
    project_id, plan = _seed_plan(db_session, object_storage, "分段首段1基", order_base=1)
    service = _service(object_storage, recorder)

    segments = service.materialize_segments(db_session, project_id=project_id)
    assert [seg.order_index for seg in segments] == [1, 2, 3]

    # 第 1 段必须能直接用分镜关键帧生成候选，而不是要求"上一段已接受"
    first = service.generate_candidate(db_session, project_id=project_id, segment_id=segments[0].id, seed=11)
    first_segment = next(seg for seg in first if seg.order_index == 1)
    assert first_segment.status == "awaiting_review"
    assert first_segment.candidates[-1].anchor_source == "scene_keyframe"
    assert len(recorder) == 1

    # 第 2 段才走续写：用上一段已接受候选的尾帧
    service.accept_candidate(
        db_session, project_id=project_id, candidate_id=first_segment.candidates[-1].id
    )
    second = service.generate_candidate(db_session, project_id=project_id, segment_id=segments[1].id, seed=22)
    second_segment = next(seg for seg in second if seg.order_index == 2)
    assert second_segment.candidates[-1].anchor_source == "previous_tail"
    assert len(recorder) == 2
