from __future__ import annotations

import io
from datetime import UTC, datetime

from PIL import Image
from sqlalchemy.orm import Session

from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.modules.content_plan.domain import STATUS_CONFIRMED, ContentPlan, ContentScene, ContentVariant
from onetake_api.modules.content_plan.repository import ContentPlanRepository
from onetake_api.modules.main_image.domain import MainImageVersion
from onetake_api.modules.main_image.repository import MainImageRepository
from onetake_api.modules.pipeline.public import PipelinePublicService
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.modules.subtitle.domain import SUBTITLE_CONFIRMED, SubtitleVersion
from onetake_api.modules.subtitle.repository import SubtitleRepository
from onetake_api.modules.video_plan.domain import BATCH_DONE, BATCH_STOPPED
from onetake_api.modules.video_plan.segment_generation import GeneratedCandidate
from onetake_api.modules.video_plan.service import VideoPlanApplicationService
from onetake_api.modules.voice.domain import VOICE_CONFIRMED, VoiceRun
from onetake_api.modules.voice.repository import VoiceRepository

WIDTH, HEIGHT = 1080, 1920


def _scene(order: int) -> ContentScene:
    start = float(order * 5)
    return ContentScene(
        scene_id=f"scene_{order}", order=order, purpose="展示", script_excerpt="文案",
        start_seconds=start, end_seconds=start + 5, shot_type="medium", prompt="商品展示",
        overlay_product=True, product_position="center", background_style="clean", template_id="clean",
        subtitle_segment_ids=[order + 1], qa_rules=[], visual_goal="product_reveal", subject_action="展示",
        camera_move="slow_push_in", product_mode="overlay", transition="fade",
    )


class FakeGenerator:
    def __init__(self, *, on_generate=None) -> None:
        self.calls: list[str] = []
        self._on_generate = on_generate

    def generate(self, *, plan, segment, scene, anchor, duration, seed, negative_prompt):
        self.calls.append(segment.id)
        if self._on_generate is not None:
            self._on_generate(segment)
        return GeneratedCandidate(
            video_bytes=b"video", tail_frame_bytes=b"tail", head_frame_bytes=b"head",
            width=plan.width, height=plan.height, fps=plan.fps,
            duration_seconds=float(duration), provider="fake",
        )


class FakeComposition:
    provider_name = "mock-video"

    def compose(self, _request):
        return b"final-video"


def _seed_plan(session: Session, storage: ObjectStoragePublicService, name: str):
    project = ProjectPublicService().create_project(session, product_name=name, product_note=None)
    now = datetime.now(UTC)
    main_key = f"projects/{project.id}/main.png"
    src = io.BytesIO()
    Image.new("RGB", (WIDTH, HEIGHT), (30, 120, 200)).save(src, format="PNG")
    storage.put_bytes(object_key=main_key, content=src.getvalue(), mime_type="image/png")
    storage.put_bytes(object_key=f"projects/{project.id}/v.wav", content=b"voice", mime_type="audio/wav")
    storage.put_bytes(object_key=f"projects/{project.id}/s.srt", content="1\n00:00:00,000 --> 00:00:02,000\n字幕\n".encode("utf-8"), mime_type="application/x-subrip")
    MainImageRepository().add(session, MainImageVersion("miv_b", project.id, "ast_b", "confirmed", "edt_b", "mat_b", main_key, None, 2000, 2000, 1000, 1000, 1000, 0.9, None, now, now, now, now))
    VoiceRepository().add(session, VoiceRun("voi_b", project.id, "scr_b", VOICE_CONFIRMED, True, True, "mock", "c", "female", "zh", 1.0, "测试。", f"projects/{project.id}/v.wav", "audio/wav", 15.0, [], None, now, now, now, now))
    SubtitleRepository().add(session, SubtitleVersion("sub_b", project.id, "scr_b", "voi_b", SUBTITLE_CONFIRMED, True, "zh", [{"index": 1, "text": "测试。", "start": 0, "end": 15}], f"projects/{project.id}/s.srt", None, now, now, now, now))
    PipelinePublicService().mark_audio_subtitle_confirmed(session, project.id)
    ContentPlanRepository().add(session, ContentPlan(
        id=f"cpl_{project.id}", project_id=project.id, script_version_id="scr_b", subtitle_version_id="sub_b",
        status=STATUS_CONFIRMED, provider="rules", model="rules-v1",
        variants=[ContentVariant("var_b", "标准", "clean", [_scene(0), _scene(1), _scene(2)])],
        selected_variant_index=0, total_duration_seconds=15.0, error_code=None, created_at=now, updated_at=now, confirmed_at=now,
    ))
    plan = VideoPlanApplicationService(storage=storage).create_plan(session, project_id=project.id, mode="product", template_id="clean").plan
    session.flush()
    return project.id, plan


def _patch_finalize(monkeypatch):
    from onetake_api.modules.video_plan import segment_service
    import onetake_api.integrations.media.video_utils as vu
    import onetake_api.integrations.mock_video.renderer as mr
    monkeypatch.setattr(vu, "concatenate_videos", lambda **_kw: b"base-video")
    monkeypatch.setattr(mr, "validate_final_video", lambda *_a, **_kw: type("M", (), {"width": 1080, "height": 1920, "fps": 30.0, "video_codec": "h264", "audio_codec": "aac"})())
    monkeypatch.setattr("onetake_api.modules.composition.service.get_composition_provider", lambda: FakeComposition())


def test_batch_resumes_from_first_unaccepted_segment(db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch) -> None:
    monkeypatch.setenv("MOCK_PROVIDERS", "true")
    monkeypatch.setenv("PRODUCT_SCENE_ENABLED", "true")
    from onetake_api.config import get_settings
    get_settings.cache_clear()
    _patch_finalize(monkeypatch)

    project_id, plan = _seed_plan(db_session, object_storage, "批量续跑")
    generator = FakeGenerator()
    from onetake_api.modules.video_plan.segment_service import VideoSegmentApplicationService
    service = VideoSegmentApplicationService(storage=object_storage, generator=generator)

    segments = service.materialize_segments(db_session, project_id=project_id)
    # 先把第 1 段接受，制造断点
    first = service.generate_candidate(db_session, project_id=project_id, segment_id=segments[0].id, seed=1)
    first_seg = next(s for s in first if s.order_index == 0)
    service.accept_candidate(db_session, project_id=project_id, candidate_id=first_seg.candidates[-1].id)
    generator.calls.clear()

    completed = service.continue_batch(db_session, project_id=project_id)
    assert completed.batch_status == BATCH_DONE
    assert completed.status == "completed"
    assert completed.final_object_key is not None
    # 只重新生成了第 2、3 段
    assert [service._segments.get(db_session, s.id).order_index for s in segments if service._segments.get(db_session, s.id).accepted_candidate_id] == [0, 1, 2]
    assert len(generator.calls) == 2


def test_batch_stops_at_segment_boundary_and_resumes(db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch) -> None:
    monkeypatch.setenv("MOCK_PROVIDERS", "true")
    monkeypatch.setenv("PRODUCT_SCENE_ENABLED", "true")
    from onetake_api.config import get_settings
    get_settings.cache_clear()
    _patch_finalize(monkeypatch)

    project_id, plan = _seed_plan(db_session, object_storage, "批量停止")
    from onetake_api.modules.video_plan.segment_service import VideoSegmentApplicationService
    holder: dict[str, object] = {}

    def stop_after_first(_segment):
        if not holder.get("stopped"):
            holder["stopped"] = True
            holder["service"].stop_batch(db_session, project_id=project_id)

    generator = FakeGenerator(on_generate=stop_after_first)
    service = VideoSegmentApplicationService(storage=object_storage, generator=generator)
    holder["service"] = service

    stopped = service.start_batch(db_session, project_id=project_id)
    assert stopped.batch_status == BATCH_STOPPED
    segments_after_stop = service.materialize_segments(db_session, project_id=project_id)
    assert sum(1 for s in segments_after_stop if s.accepted_candidate_id) == 1

    resumed = service.continue_batch(db_session, project_id=project_id)
    assert resumed.batch_status == BATCH_DONE
    assert resumed.status == "completed"
    final_segments = service.materialize_segments(db_session, project_id=project_id)
    assert all(s.accepted_candidate_id for s in final_segments)
