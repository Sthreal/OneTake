"""批次 4a-2 集成测：空镜由免 Key 素材填充（并证明"开关关闭时一个调用都不少"）。

生成器用假实现（记录调用），素材填充用打桩的 `fill_from_stock`（内容是真 ffmpeg 归一化出来的），
所以这里既验证**接线**，也验证"素材片段的形状能通过管线自检（尺寸一致）"。
"""
from __future__ import annotations

import io
import json
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image
from imageio_ffmpeg import get_ffmpeg_exe
from sqlalchemy.orm import Session

from onetake_api.config import get_settings
from onetake_api.integrations.media.video_utils import inspect_video_duration
from onetake_api.integrations.mock_video.renderer import render_base_video
from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.integrations.stock import clip as stock_clip
from onetake_api.integrations.stock.domain import SOURCE_WIKIMEDIA, StockAsset, StockError, StockLicense
from onetake_api.integrations.stock.fill import StockFill
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

WIDTH, HEIGHT = 360, 640


@dataclass
class _Generated:
    video_bytes: bytes
    provider_name: str = "wan-i2v"


class _RecordingAdapter:
    """假 i2v：把锚点图渲成 1 秒短片，并记录被调用次数。"""

    def __init__(self, calls: list[bytes], *, width: int, height: int) -> None:
        self._calls = calls
        self._width = width
        self._height = height
        self.provider_name = "wan-i2v"

    def generate(self, *, image_bytes: bytes, prompt: str, duration_seconds: int, negative_prompt: str | None = None):
        self._calls.append(image_bytes)
        video = render_base_video(
            image_bytes=image_bytes, mode="product", template_id="clean",
            duration_seconds=1.0, width=self._width, height=self._height, fps=24,
        )
        return video, "task"


def _scene(order: int, *, product_mode: str, stock_query: str = "") -> ContentScene:
    start = float((order - 1) * 4)
    return ContentScene(
        scene_id=f"scene_{order}", order=order, purpose="hook" if product_mode == "absent" else "展示",
        script_excerpt="文案", start_seconds=start, end_seconds=start + 4, shot_type="lifestyle_scene",
        prompt="场景", overlay_product=product_mode != "absent", product_position="center",
        background_style="clean", template_id="clean", subtitle_segment_ids=[order], qa_rules=[],
        visual_goal="pain_point" if product_mode == "absent" else "product_reveal",
        subject_action="缓慢推进", camera_move="slow_push_in", product_mode=product_mode,
        transition="fade", stock_query=stock_query,
    )


def _seed(db: Session, storage: ObjectStoragePublicService, name: str):
    project = ProjectPublicService().create_project(db, product_name=name, product_note=None)
    now = datetime.now(UTC)
    main_key = f"projects/{project.id}/main.png"
    buffer = io.BytesIO()
    Image.new("RGB", (WIDTH, HEIGHT), (200, 60, 60)).save(buffer, format="PNG")
    storage.put_bytes(object_key=main_key, content=buffer.getvalue(), mime_type="image/png")
    MainImageRepository().add(db, MainImageVersion("miv", project.id, "ast", "confirmed", "edt", "mat", main_key, None, 2000, 2000, 1000, 1000, 1000, 0.9, None, now, now, now, now))
    VoiceRepository().add(db, VoiceRun("voi", project.id, "scr", VOICE_CONFIRMED, True, True, "mock", "cosyvoice-v2", "female", "zh", 1.0, "测试。", f"projects/{project.id}/v.wav", "audio/wav", 8.0, [], None, now, now, now, now))
    SubtitleRepository().add(db, SubtitleVersion("sub", project.id, "scr", "voi", SUBTITLE_CONFIRMED, True, "zh", [{"index": 1, "text": "测试。", "start": 0, "end": 8}], f"projects/{project.id}/s.srt", None, now, now, now, now))
    PipelinePublicService().mark_audio_subtitle_confirmed(db, project.id)
    ContentPlanRepository().add(db, ContentPlan(
        id="cpl", project_id=project.id, script_version_id="scr", subtitle_version_id="sub",
        status=STATUS_CONFIRMED, provider="rules", model="rules-v1",
        variants=[ContentVariant("var", "标准", "clean", [
            _scene(1, product_mode="absent", stock_query="morning desk"),   # 空镜：可以让素材填
            _scene(2, product_mode="overlay"),                             # 非空镜：绝不能填
        ])],
        selected_variant_index=0, total_duration_seconds=8.0, error_code=None,
        created_at=now, updated_at=now, confirmed_at=now,
    ))
    plan = VideoPlanApplicationService(storage=storage).create_plan(
        db, project_id=project.id, mode="product", template_id="clean"
    ).plan
    db.flush()
    for order in (1, 2):
        _accept_keyframe(db, storage, project.id, f"scene_{order}")
    return project.id, plan


def _accept_keyframe(db: Session, storage: ObjectStoragePublicService, project_id: str, scene_id: str) -> None:
    import io as _io

    from onetake_api.modules.video_plan.keyframe_domain import KEYFRAME_READY, VideoKeyframeCandidate
    from onetake_api.modules.video_plan.keyframe_repository import VideoKeyframeCandidateRepository
    from onetake_api.modules.video_plan.keyframe_service import VideoKeyframeApplicationService

    image = Image.new("RGB", (WIDTH, HEIGHT), (200, 60, 60))
    buffer = _io.BytesIO()
    image.save(buffer, format="PNG")
    object_key = f"projects/{project_id}/keyframes/stock/{scene_id}.png"
    storage.put_bytes(object_key=object_key, content=buffer.getvalue(), mime_type="image/png")
    repository = VideoKeyframeCandidateRepository()
    candidate = VideoKeyframeCandidate(
        id=f"kfc_{scene_id}", project_id=project_id, content_plan_id="cpl", scene_id=scene_id,
        order_index=1, mode="integrated", status=KEYFRAME_READY, provider="test",
        created_at=datetime.now(UTC), image_object_key=object_key, width=WIDTH, height=HEIGHT,
    )
    repository.add(db, candidate)
    db.flush()
    VideoKeyframeApplicationService(storage=storage).accept_candidate(db, project_id=project_id, keyframe_id=candidate.id)


def _service(storage, calls: list[bytes]):
    from onetake_api.modules.video_plan.segment_service import VideoSegmentApplicationService

    generator = SegmentVideoGenerator(
        storage=storage,
        adapter_factory=lambda plan: _RecordingAdapter(calls, width=plan.width, height=plan.height),
        # 首尾帧（kf2v）工厂显式返回 None：本测只关心"有没有走 i2v 生成器"，不想被成对适配器分流
        pair_adapter_factory=lambda plan: None,
        frame_runner=SegmentTailFrameExtractor(offset_frames=2),
    )
    return VideoSegmentApplicationService(storage=storage, generator=generator)


def _stock_clip_bytes(width: int, height: int, seconds: float = 4.0) -> bytes:
    """真造一段"素材归一化后"的片段（与目标规格一致、静音）。"""
    with tempfile.TemporaryDirectory() as temp_dir:
        source = Path(temp_dir) / "src.mp4"
        subprocess.run(
            [get_ffmpeg_exe(), "-y", "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=24:duration=1",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)],
            check=True, capture_output=True,
        )
        return stock_clip.normalize_clip(
            source_bytes=source.read_bytes(), duration_seconds=seconds, width=width, height=height, fps=24,
        )


def _fake_fill(width: int, height: int, video: bytes):
    def fake(*, query: str, duration_seconds: float, width: int_, height: int_, fps: int, **kwargs):
        head, tail = stock_clip.head_and_tail_frames(video)
        return StockFill(
            asset=StockAsset(
                asset_id="pageid-1", kind="video", source=SOURCE_WIKIMEDIA, provider="wikimedia-commons",
                title="Morning desk", download_url="https://cdn.example/clip.webm",
                landing_url="https://commons.example/File:Morning_desk.webm", creator="Someone",
                license=StockLicense("CC BY-SA 4.0"),
            ),
            video_bytes=video, head_frame_bytes=head, tail_frame_bytes=tail,
            duration_seconds=float(duration_seconds), width=width, height=height, fps=fps,
            provider="stock:wikimedia",
        )
    # 用真实签名里的名字（width/height 会遮蔽闭包变量，这里显式绑定）
    def bound(*, query: str, duration_seconds: float, width: int, height: int, fps: int, **kwargs):
        head, tail = stock_clip.head_and_tail_frames(video)
        return StockFill(
            asset=StockAsset(
                asset_id="pageid-1", kind="video", source=SOURCE_WIKIMEDIA, provider="wikimedia-commons",
                title="Morning desk", download_url="https://cdn.example/clip.webm",
                landing_url="https://commons.example/File:Morning_desk.webm", creator="Someone",
                license=StockLicense("CC BY-SA 4.0"),
            ),
            video_bytes=video, head_frame_bytes=head, tail_frame_bytes=tail,
            duration_seconds=float(duration_seconds), width=width, height=height, fps=fps,
            provider="stock:wikimedia",
        )
    return bound


def _env(monkeypatch, *, stock_enabled: bool) -> None:
    monkeypatch.setenv("MOCK_PROVIDERS", "true")
    monkeypatch.setenv("PRODUCT_SCENE_ENABLED", "true")
    monkeypatch.setenv("VIDEO_CONTINUITY_ENABLED", "true")
    monkeypatch.setenv("STOCK_ENABLED", "true" if stock_enabled else "false")
    get_settings.cache_clear()


def _segment_for(db: Session, project_id: str, service, scene_id: str):
    segments = service.materialize_segments(db, project_id=project_id)
    return next(item for item in segments if item.scene_id == scene_id), segments


def test_absent_shot_is_filled_from_stock_without_calling_generator(
    db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    _env(monkeypatch, stock_enabled=True)
    project_id, plan = _seed(db_session, object_storage, "空镜素材填充")
    calls: list[bytes] = []
    service = _service(object_storage, calls)
    video = _stock_clip_bytes(plan.width, plan.height, seconds=4.0)
    monkeypatch.setattr(
        "onetake_api.modules.video_plan.segment_service.fill_from_stock",
        _fake_fill(plan.width, plan.height, video),
    )

    segment, _ = _segment_for(db_session, project_id, service, "scene_1")
    segments = service.generate_candidate(db_session, project_id=project_id, segment_id=segment.id)
    candidate = next(item for item in segments if item.scene_id == "scene_1").candidates[-1]

    assert candidate.provider == "stock:wikimedia"                      # 用的是素材
    assert calls == []                                                  # 生成器一次都没调 → 省钱
    stored = b"".join(object_storage.read_object(object_key=candidate.video_object_key))
    assert stored == video                                              # 存的确实是归一化后的素材片段
    assert abs(inspect_video_duration(stored) - 4.0) <= 0.2
    assert candidate.width == plan.width and candidate.height == plan.height
    assert candidate.tail_frame_object_key and candidate.head_frame_object_key
    # CC 署名必须**留痕**（交付门会读它提醒用户）
    sidecar_key = candidate.video_object_key.replace("/video.mp4", "/stock-attribution.json")
    payload = json.loads(b"".join(object_storage.read_object(object_key=sidecar_key)).decode("utf-8"))
    assert payload["license"] == "CC BY-SA 4.0" and "CC BY-SA 4.0" in payload["attribution"]
    assert payload["asset_id"] == "pageid-1" and payload["source"] == "wikimedia"


def test_stock_disabled_keeps_original_generation_path(
    db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    """开关关闭时：一个调用都不少、也不解析任何检索词（默认零变更）。"""
    _env(monkeypatch, stock_enabled=False)
    project_id, plan = _seed(db_session, object_storage, "空镜开关关闭")
    calls: list[bytes] = []
    service = _service(object_storage, calls)
    monkeypatch.setattr(
        "onetake_api.modules.video_plan.segment_service.fill_from_stock",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("关闭开关时不该走素材路径")),
    )

    segment, _ = _segment_for(db_session, project_id, service, "scene_1")
    segments = service.generate_candidate(db_session, project_id=project_id, segment_id=segment.id)
    candidate = next(item for item in segments if item.scene_id == "scene_1").candidates[-1]

    # 原生成路径（注入的假 i2v）被调用过，且产物不是素材
    assert candidate.provider == "wan-i2v" and calls


def test_non_absent_scene_never_uses_stock(
    db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    """非空镜（商品必须在帧内）绝不允许被通用素材顶替。"""
    _env(monkeypatch, stock_enabled=True)
    project_id, _plan = _seed(db_session, object_storage, "非空镜不许填")
    calls: list[bytes] = []
    service = _service(object_storage, calls)
    monkeypatch.setattr(
        "onetake_api.modules.video_plan.segment_service.fill_from_stock",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("非空镜不该走素材路径")),
    )

    segments = service.materialize_segments(db_session, project_id=project_id)
    second = next(item for item in segments if item.scene_id == "scene_2")
    result = service.generate_candidate(db_session, project_id=project_id, segment_id=second.id)
    candidate = next(item for item in result if item.scene_id == "scene_2").candidates[-1]

    assert candidate.provider == "wan-i2v" and calls   # 走原生成路径（注入的假 i2v 被调用）


def test_stock_failure_falls_back_to_generator(
    db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    """素材报错（源挂了 / 半路失败）→ 回退原生成路径，成片不受影响。"""
    _env(monkeypatch, stock_enabled=True)
    project_id, _plan = _seed(db_session, object_storage, "素材失败回退")
    calls: list[bytes] = []
    service = _service(object_storage, calls)

    def boom(**_kwargs):
        raise StockError("源挂了")

    monkeypatch.setattr("onetake_api.modules.video_plan.segment_service.fill_from_stock", boom)

    segment, _ = _segment_for(db_session, project_id, service, "scene_1")
    segments = service.generate_candidate(db_session, project_id=project_id, segment_id=segment.id)
    candidate = next(item for item in segments if item.scene_id == "scene_1").candidates[-1]

    assert candidate.provider == "wan-i2v" and calls   # 走原生成路径（注入的假 i2v 被调用）
