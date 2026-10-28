from __future__ import annotations

import io
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image
from sqlalchemy.orm import Session

from onetake_api.integrations.media.video_utils import inspect_video_duration
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


def _accept_keyframe(session: Session, storage: ObjectStoragePublicService, project_id: str, scene_id: str) -> None:
    """M4-03 提交 2 起：商品段**必须**有已采用的入画关键帧（背景回退已废弃）。

    这里直接写入一个 ready 候选并采用，而不走 `generate_candidate`：本文件被测的是
    **锚点 / 续写逻辑**，不是关键帧生成；直接造数据能去掉 QA 耦合，让用例更聚焦、更稳定。
    """
    import io
    from datetime import UTC, datetime

    from PIL import Image

    from onetake_api.modules.video_plan.keyframe_domain import KEYFRAME_READY, VideoKeyframeCandidate
    from onetake_api.modules.video_plan.keyframe_repository import VideoKeyframeCandidateRepository
    from onetake_api.modules.video_plan.keyframe_service import VideoKeyframeApplicationService

    image = Image.new("RGB", (360, 640), (200, 60, 60))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    object_key = f"projects/{project_id}/keyframes/test/{scene_id}.png"
    storage.put_bytes(object_key=object_key, content=buffer.getvalue(), mime_type="image/png")

    repository = VideoKeyframeCandidateRepository()
    candidate = VideoKeyframeCandidate(
        id=f"kfc_{scene_id}", project_id=project_id, content_plan_id="cpl_test", scene_id=scene_id,
        order_index=1, mode="integrated", status=KEYFRAME_READY, provider="test",
        created_at=datetime.now(UTC), image_object_key=object_key, width=360, height=640,
    )
    repository.add(session, candidate)
    session.flush()
    VideoKeyframeApplicationService(storage=storage).accept_candidate(
        session, project_id=project_id, keyframe_id=candidate.id
    )

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
    # 场景 id 由 _make_scene 生成：order_base=0 时是 scene_0/1/2
    _accept_keyframe(db_session, object_storage, project_id, "scene_0")
    service = _service(object_storage, recorder)

    segments = service.materialize_segments(db_session, project_id=project_id)
    assert [seg.order_index for seg in segments] == [0, 1, 2]

    first = service.generate_candidate(db_session, project_id=project_id, segment_id=segments[0].id, seed=11)
    first_segment = next(seg for seg in first if seg.order_index == 0)
    assert first_segment.status == "awaiting_review"
    first_candidate = first_segment.candidates[-1]
    assert first_candidate.anchor_source == "integrated_keyframe"
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

def test_first_segment_uses_integrated_keyframe_with_one_based_scene_order(
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
    _accept_keyframe(db_session, object_storage, project_id, "scene_1")
    service = _service(object_storage, recorder)

    segments = service.materialize_segments(db_session, project_id=project_id)
    assert [seg.order_index for seg in segments] == [1, 2, 3]

    # 第 1 段必须能直接用分镜关键帧生成候选，而不是要求"上一段已接受"
    first = service.generate_candidate(db_session, project_id=project_id, segment_id=segments[0].id, seed=11)
    first_segment = next(seg for seg in first if seg.order_index == 1)
    assert first_segment.status == "awaiting_review"
    assert first_segment.candidates[-1].anchor_source == "integrated_keyframe"
    assert len(recorder) == 1

    # 第 2 段才走续写：用上一段已接受候选的尾帧
    service.accept_candidate(
        db_session, project_id=project_id, candidate_id=first_segment.candidates[-1].id
    )
    second = service.generate_candidate(db_session, project_id=project_id, segment_id=segments[1].id, seed=22)
    second_segment = next(seg for seg in second if seg.order_index == 2)
    assert second_segment.candidates[-1].anchor_source == "previous_tail"
    assert len(recorder) == 2


class FakeHonoringDuration:
    """假适配器：**如实按请求时长**渲染（不再对时长撒谎）。

    为什么要单独一个：旧的 `FakeWanI2V` 无论被请求几秒都只渲 1 秒 —— 那恰好掩盖了
    "超过单次上限被静默钳制"这类缺陷（假适配器说 5 秒、真适配器给 5 秒、目标却是 7 秒）。
    """

    def __init__(self, recorder: list[bytes], *, width: int, height: int) -> None:
        self._recorder = recorder
        self._width = width
        self._height = height
        self.provider_name = "wan-i2v"

    def generate(self, *, image_bytes: bytes, prompt: str, duration_seconds: int, negative_prompt: str | None = None):
        self._recorder.append(image_bytes)
        video = render_base_video(
            image_bytes=image_bytes, mode="product", template_id="clean",
            duration_seconds=float(duration_seconds), width=self._width, height=self._height, fps=24,
        )
        return video, "task"


def test_segment_over_limit_is_split_and_stitched_not_clamped(
    db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    """回归：超过单次上限的镜必须**切分后拼接**，而不是被静默钳到上限。

    改动前的实测缺陷：7 秒镜（`WAN_I2V_MAX_SECONDS=5`）只生成 5 秒 → 四镜拼接后成片 16 秒，
    而计划与配音是 18 秒 → 成片**比配音短 2 秒**（最后 2 秒有语音没画面）。
    """
    monkeypatch.setenv("MOCK_PROVIDERS", "true")
    monkeypatch.setenv("VIDEO_CONTINUITY_ENABLED", "true")
    monkeypatch.setenv("WAN_I2V_MAX_SECONDS", "3")      # 单次上限压到 3 秒，方便用 5 秒镜触发切分
    from onetake_api.config import get_settings
    get_settings.cache_clear()

    recorder: list[bytes] = []
    project_id, plan = _seed_plan(db_session, object_storage, "分段切分")
    _accept_keyframe(db_session, object_storage, project_id, "scene_0")
    from onetake_api.modules.video_plan.segment_generation import SegmentVideoGenerator
    from onetake_api.modules.video_plan.segment_service import VideoSegmentApplicationService

    generator = SegmentVideoGenerator(
        storage=object_storage,
        adapter_factory=lambda plan: FakeHonoringDuration(recorder, width=plan.width, height=plan.height),
        frame_runner=SegmentTailFrameExtractor(offset_frames=2),
    )
    service = VideoSegmentApplicationService(storage=object_storage, generator=generator)
    segments = service.materialize_segments(db_session, project_id=project_id)

    generated = service.generate_candidate(db_session, project_id=project_id, segment_id=segments[0].id, seed=7)
    segment = next(seg for seg in generated if seg.order_index == 0)
    candidate = segment.candidates[-1]

    # 5 秒镜 + 3 秒上限 → 2 次调用（3 + 2），而不是 1 次被钳成 3 秒
    assert len(recorder) == 2, f"应切分成 2 次调用，实际 {len(recorder)} 次"
    # 子片段首尾相接：第 2 次拿到的首帧必须**不同于**第 1 次（= 第 1 片的尾帧，不是同一张锚点）
    assert _raw_rgb(recorder[1]) != _raw_rgb(recorder[0])
    # 候选声明的时长 = 计划时长；真实视频时长也必须对得上（自检通过才会落库）
    assert candidate.duration_seconds == 5.0
    video = b"".join(object_storage.read_object(object_key=candidate.video_object_key))
    assert abs(inspect_video_duration(video) - 5.0) <= 0.5

class _ProbeGenerator:
    """把"生成当中"这一刻**读库**探出来（真实调用要几十秒，这段状态必须可观测）。"""

    def __init__(self, *, session: Session, segment_ids: list[str], boom: Exception | None = None) -> None:
        self._session = session
        self._segment_ids = segment_ids
        self._boom = boom
        self.seen: list[str] = []

    def generate(self, *, plan, segment, scene, anchor, duration, seed, negative_prompt):
        if self._boom is not None:
            raise self._boom
        from onetake_api.modules.video_plan.segment_repository import VideoSegmentRepository

        self._session.expire_all()
        latest = VideoSegmentRepository().get(self._session, segment.id)
        self.seen.append(latest.status if latest is not None else "missing")
        return _GeneratedForProbe(plan=plan, duration=duration)


class _GeneratedForProbe:
    def __init__(self, *, plan, duration: int) -> None:
        self.video_bytes = b"video"
        self.tail_frame_bytes = b"tail"
        self.head_frame_bytes = b"head"
        self.width = plan.width
        self.height = plan.height
        self.fps = plan.fps
        self.duration_seconds = float(duration)
        self.provider = "probe"
        self.attribution = None


def test_segment_is_marked_generating_while_the_provider_runs(
    db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    """2026-10-16 用户实测：点「逐段推进一段」后界面看不到任何状态，以为坏了。

    真实调用一段要 30~90 秒，所以"生成中"必须**落库**（同进程读库都要能看到），否则刷新/轮询
    只能看到上一次的 planned。
    """
    monkeypatch.setenv("MOCK_PROVIDERS", "true")
    monkeypatch.setenv("PRODUCT_SCENE_ENABLED", "true")
    from onetake_api.config import get_settings

    get_settings.cache_clear()

    project_id, _plan = _seed_plan(db_session, object_storage, "生成中可见", order_base=1)
    _accept_keyframe(db_session, object_storage, project_id, "scene_1")
    from onetake_api.modules.video_plan.segment_service import VideoSegmentApplicationService

    probe = _ProbeGenerator(session=db_session, segment_ids=[])
    service = VideoSegmentApplicationService(storage=object_storage, generator=probe)
    segments = service.materialize_segments(db_session, project_id=project_id)

    service.generate_candidate(db_session, project_id=project_id, segment_id=segments[0].id, seed=1)

    assert probe.seen == ["generating"], probe.seen
    refreshed = next(seg for seg in service.materialize_segments(db_session, project_id=project_id) if seg.order_index == 1)
    assert refreshed.status == "awaiting_review"


def test_failed_generation_falls_to_failed_not_generating(
    db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    """生成失败不能把那段留在"生成中"（否则页面永远显示生成中，人只能重跑）。"""
    monkeypatch.setenv("MOCK_PROVIDERS", "true")
    monkeypatch.setenv("PRODUCT_SCENE_ENABLED", "true")
    from onetake_api.config import get_settings

    get_settings.cache_clear()

    project_id, _plan = _seed_plan(db_session, object_storage, "生成失败落失败", order_base=1)
    _accept_keyframe(db_session, object_storage, project_id, "scene_1")
    from onetake_api.modules.video_plan.segment_service import VideoSegmentApplicationService

    probe = _ProbeGenerator(session=db_session, segment_ids=[], boom=RuntimeError("供应商炸了"))
    service = VideoSegmentApplicationService(storage=object_storage, generator=probe)
    segments = service.materialize_segments(db_session, project_id=project_id)

    try:
        service.generate_candidate(db_session, project_id=project_id, segment_id=segments[0].id, seed=1)
    except RuntimeError:
        pass
    else:  # pragma: no cover - 生成器必须把异常抛出来
        raise AssertionError("生成失败必须抛出，不能静默")

    db_session.expire_all()
    from onetake_api.modules.video_plan.segment_repository import VideoSegmentRepository

    failed = VideoSegmentRepository().get(db_session, segments[0].id)
    assert failed is not None
    assert failed.status == "failed", failed.status
    assert failed.last_error == "RuntimeError"