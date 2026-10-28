from __future__ import annotations

import io
from dataclasses import replace
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
from onetake_api.modules.video_plan.domain import BATCH_DONE, BATCH_RUNNING, BATCH_STOPPED
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


def _accept_keyframe(session: Session, storage: ObjectStoragePublicService, project_id: str, scene_id: str) -> None:
    """M4-03 提交 2 起：商品段**必须**有已采用的入画关键帧（背景回退已废弃）。

    直接写入 ready 候选并采用：本文件测的是批处理编排，不是关键帧生成，去掉 QA 耦合更聚焦。
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
    _accept_keyframe(db_session, object_storage, project_id, "scene_0")
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
    # S1：base 视频 key 不能被抹掉（旧实现用 `replace(plan, …)` 会把它丢掉）
    assert completed.base_video_object_key == f"projects/{project_id}/video/{plan.id}/base.mp4"
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
    _accept_keyframe(db_session, object_storage, project_id, "scene_0")
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
    assert resumed.base_video_object_key is not None
    assert resumed.status == "completed"
    final_segments = service.materialize_segments(db_session, project_id=project_id)
    assert all(s.accepted_candidate_id for s in final_segments)


def test_batch_steps_one_segment_per_call_and_keeps_running(
    db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    """S2：`stop_after_segments=1` 每次只前进一段、保持 running；最后一段走完才合成。"""
    monkeypatch.setenv("MOCK_PROVIDERS", "true")
    monkeypatch.setenv("PRODUCT_SCENE_ENABLED", "true")
    from onetake_api.config import get_settings

    get_settings.cache_clear()
    _patch_finalize(monkeypatch)

    project_id, plan = _seed_plan(db_session, object_storage, "批量步进")
    _accept_keyframe(db_session, object_storage, project_id, "scene_0")
    generator = FakeGenerator()
    from onetake_api.modules.video_plan.segment_service import VideoSegmentApplicationService

    service = VideoSegmentApplicationService(storage=object_storage, generator=generator)

    def accepted_count() -> int:
        return sum(
            1 for item in service.materialize_segments(db_session, project_id=project_id) if item.accepted_candidate_id
        )

    first = service.continue_batch(db_session, project_id=project_id, stop_after_segments=1)
    assert first.batch_status == BATCH_RUNNING
    assert first.status != "completed"
    assert accepted_count() == 1
    assert len(generator.calls) == 1

    second = service.continue_batch(db_session, project_id=project_id, stop_after_segments=1)
    assert second.batch_status == BATCH_RUNNING
    assert accepted_count() == 2
    assert len(generator.calls) == 2

    third = service.continue_batch(db_session, project_id=project_id, stop_after_segments=1)
    assert third.batch_status == BATCH_DONE
    assert third.status == "completed"
    assert accepted_count() == 3
    assert len(generator.calls) == 3
    assert third.base_video_object_key is not None


def test_new_plan_defaults_to_auto_realism_and_that_tier_drives_the_prompt(
    db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    """S5 口径 5：**新项目 auto**（老项目由迁移 0024 写 `off`），且档位真的决定分段提示词。"""
    from dataclasses import replace

    from onetake_api.modules.video_plan.segment_generation import assemble_segment_prompt

    monkeypatch.setenv("MOCK_PROVIDERS", "true")
    monkeypatch.setenv("PRODUCT_SCENE_ENABLED", "true")
    from onetake_api.config import get_settings

    get_settings.cache_clear()
    project_id, plan = _seed_plan(db_session, object_storage, "真实感档")
    assert plan.motion_realism == "auto"

    scene = _scene(0)
    assert "光线：" in assemble_segment_prompt(scene, plan)
    assert "光线：" not in assemble_segment_prompt(scene, replace(plan, motion_realism="off"))


def test_seam_modes_choose_the_right_anchor(
    db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    """S6：pin=钉帧（尾帧取下一镜关键帧）/ tail=续拍（首帧取上一段真实尾帧）/ off=各镜独立。"""
    from dataclasses import replace

    monkeypatch.setenv("MOCK_PROVIDERS", "true")
    monkeypatch.setenv("PRODUCT_SCENE_ENABLED", "true")
    from onetake_api.config import get_settings

    get_settings.cache_clear()
    _patch_finalize(monkeypatch)

    project_id, plan = _seed_plan(db_session, object_storage, "接缝模式")
    _accept_keyframe(db_session, object_storage, project_id, "scene_0")
    _accept_keyframe(db_session, object_storage, project_id, "scene_1")
    from onetake_api.modules.video_plan.segment_service import VideoSegmentApplicationService

    service = VideoSegmentApplicationService(storage=object_storage, generator=FakeGenerator())
    segments = service.materialize_segments(db_session, project_id=project_id)
    first, second = segments[0], segments[1]

    # pin（默认）：首帧=本镜关键帧，尾帧=下一镜关键帧
    pinned = service._resolve_anchor(db_session, first, None, _scene(0), _scene(1), plan, True)
    assert pinned.source == "integrated_keyframe"
    assert pinned.end_frame_bytes is not None

    # off：各镜独立 —— 不带尾帧
    isolated = service._resolve_anchor(
        db_session, first, None, _scene(0), _scene(1), replace(plan, seam_mode="off"), True
    )
    assert isolated.source == "integrated_keyframe"
    assert isolated.end_frame_bytes is None

    # 先生成并采纳第 1 段，才有"真实尾帧"可续
    service.generate_candidate(db_session, project_id=project_id, segment_id=first.id, seed=1)
    refreshed = service._segments.get(db_session, first.id)
    service.accept_candidate(db_session, project_id=project_id, candidate_id=refreshed.candidates[-1].id)
    refreshed = service._segments.get(db_session, first.id)

    # tail：首帧 = 上一段已采纳候选的真实尾帧
    continued = service._resolve_anchor(
        db_session, second, refreshed, _scene(1), None, replace(plan, seam_mode="tail"), True
    )
    assert continued.source == "previous_tail"

    # tail 但第一段无上一段可续 → 退回钉帧（不报错）
    fallback = service._resolve_anchor(
        db_session, first, None, _scene(0), _scene(1), replace(plan, seam_mode="tail"), True
    )
    assert fallback.source == "integrated_keyframe"


def test_segment_seam_overrides_the_plan_setting(
    db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    """S4-③：**段级接缝覆盖方案级**（双向都要成立），清除覆盖后回落到方案级。"""
    monkeypatch.setenv("MOCK_PROVIDERS", "true")
    monkeypatch.setenv("PRODUCT_SCENE_ENABLED", "true")
    from onetake_api.config import get_settings

    get_settings.cache_clear()
    _patch_finalize(monkeypatch)

    project_id, plan = _seed_plan(db_session, object_storage, "段级接缝")
    _accept_keyframe(db_session, object_storage, project_id, "scene_0")
    _accept_keyframe(db_session, object_storage, project_id, "scene_1")
    from onetake_api.modules.video_plan.segment_service import VideoSegmentApplicationService

    service = VideoSegmentApplicationService(storage=object_storage, generator=FakeGenerator())
    first = service.materialize_segments(db_session, project_id=project_id)[0]

    # 方案级 pin（默认）→ 有尾帧
    assert service._resolve_anchor(db_session, first, None, _scene(0), _scene(1), plan, True).end_frame_bytes is not None

    # 段级 off 覆盖方案级 pin → 无尾帧
    service.set_segment_seam_mode(db_session, project_id=project_id, segment_id=first.id, seam_mode="off")
    first = service._segments.get(db_session, first.id)
    assert first.seam_mode == "off"
    assert service._resolve_anchor(db_session, first, None, _scene(0), _scene(1), plan, True).end_frame_bytes is None

    # 方案级 off + 段级 pin → 有尾帧（反向也成立）
    service.set_segment_seam_mode(db_session, project_id=project_id, segment_id=first.id, seam_mode="pin")
    first = service._segments.get(db_session, first.id)
    assert service._resolve_anchor(
        db_session, first, None, _scene(0), _scene(1), replace(plan, seam_mode="off"), True
    ).end_frame_bytes is not None

    # 清除覆盖（None）→ 回落到方案级
    service.set_segment_seam_mode(db_session, project_id=project_id, segment_id=first.id, seam_mode=None)
    first = service._segments.get(db_session, first.id)
    assert first.seam_mode is None


def test_plan_compose_overrides_reach_the_composer(
    db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    """S4-④a：方案级合成旋钮必须**真的传到 composer** —— 否则 UI 上就是「改了没用」。"""
    monkeypatch.setenv("MOCK_PROVIDERS", "true")
    monkeypatch.setenv("PRODUCT_SCENE_ENABLED", "true")
    from onetake_api.config import get_settings

    get_settings.cache_clear()
    _patch_finalize(monkeypatch)

    captured: dict[str, object] = {}

    class RecordingComposition:
        provider_name = "recording"

        def compose(self, request):
            captured["caption_style"] = request.caption_style
            captured["bgm_enabled"] = request.bgm_enabled
            captured["bgm_gain_db"] = request.bgm_gain_db
            return b"final-video"

    # 覆盖顺序要紧：_patch_finalize 也会设 composition provider，所以放在它之后
    monkeypatch.setattr(
        "onetake_api.modules.composition.service.get_composition_provider", lambda: RecordingComposition()
    )

    project_id, plan = _seed_plan(db_session, object_storage, "合成旋钮")
    _accept_keyframe(db_session, object_storage, project_id, "scene_0")
    from onetake_api.modules.video_plan.repository import VideoPlanRepository

    VideoPlanRepository().update(
        db_session, replace(plan, caption_style="karaoke", bgm_enabled=True, bgm_gain_db=-8.0)
    )
    db_session.flush()

    from onetake_api.modules.video_plan.segment_service import VideoSegmentApplicationService

    service = VideoSegmentApplicationService(storage=object_storage, generator=FakeGenerator())
    service.continue_batch(db_session, project_id=project_id)

    assert captured["caption_style"] == "karaoke"
    assert captured["bgm_enabled"] is True
    assert captured["bgm_gain_db"] == -8.0
