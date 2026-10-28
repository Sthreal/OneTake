"""Phase 3 集成测试：整片一次生成的编排（切分规则、关键帧引用、拼接）。

MOCK_PROVIDERS=true 下跑同一条分支：mock 用首帧渲染每段视频，再拼接成整片。
"""
from __future__ import annotations

from datetime import UTC, datetime

from PIL import Image, ImageDraw
from sqlalchemy.orm import Session
from io import BytesIO

from onetake_api.integrations.media.video_utils import inspect_video_dimensions
from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.modules.content_plan.domain import STATUS_CONFIRMED, ContentPlan, ContentScene, ContentVariant
from onetake_api.modules.content_plan.repository import ContentPlanRepository
from onetake_api.modules.main_image.domain import MainImageVersion
from onetake_api.modules.main_image.repository import MainImageRepository
from onetake_api.modules.pipeline.public import PipelinePublicService
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.modules.subtitle.domain import SUBTITLE_CONFIRMED, SubtitleVersion
from onetake_api.modules.subtitle.repository import SubtitleRepository
from onetake_api.modules.video_plan.keyframe_service import VideoKeyframeApplicationService
from onetake_api.modules.video_plan.service import VideoPlanApplicationService
from onetake_api.modules.voice.domain import VOICE_CONFIRMED, VoiceRun
from onetake_api.modules.voice.repository import VoiceRepository


def _png() -> bytes:
    image = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((40, 90, 472, 442), radius=40, fill=(30, 120, 200, 255))
    draw.rectangle((70, 140, 442, 175), fill=(255, 255, 255, 255))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _scene(order: int, start: float, end: float) -> ContentScene:
    return ContentScene(
        scene_id=f"scene_{order}", order=order, purpose="展示", script_excerpt=f"第{order}句台词",
        start_seconds=start, end_seconds=end, shot_type="medium", prompt="",
        overlay_product=True, product_position="center", background_style="clean", template_id="clean",
        subtitle_segment_ids=[order], qa_rules=[], visual_goal="product_reveal", subject_action="展示商品",
        camera_move="push_in", product_mode="integrated", transition="fade",
    )


def _seed(session: Session, storage: ObjectStoragePublicService, *, spans: list[tuple[float, float]], name: str) -> str:
    project = ProjectPublicService().create_project(session, product_name=name, product_note=None)
    now = datetime.now(UTC)
    image_key = f"projects/{project.id}/main.png"
    storage.put_bytes(object_key=image_key, content=_png(), mime_type="image/png")
    MainImageRepository().add(session, MainImageVersion(
        "miv_film", project.id, "ast_film", "confirmed", "edt_film", "mat_film", image_key, None,
        2000, 2000, 1000, 1000, 1000, 0.82, None, now, now, now, now,
    ))
    VoiceRepository().add(session, VoiceRun(
        "voi_film", project.id, "scr_film", VOICE_CONFIRMED, True, True, "mock", "cosyvoice-v2",
        "female", "zh", 1.0, "测试文案。", f"projects/{project.id}/voice.wav", "audio/wav", 18.0,
        [], None, now, now, now, now,
    ))
    SubtitleRepository().add(session, SubtitleVersion(
        "sub_film", project.id, "scr_film", "voi_film", SUBTITLE_CONFIRMED, True, "zh",
        [{"index": 1, "text": "测试文案。", "start": 0, "end": 18}],
        f"projects/{project.id}/subtitle.srt", None, now, now, now, now,
    ))
    PipelinePublicService().mark_audio_subtitle_confirmed(session, project.id)
    scenes = [_scene(index + 1, start, end) for index, (start, end) in enumerate(spans)]
    ContentPlanRepository().add(session, ContentPlan(
        id=f"cpl_film_{len(spans)}", project_id=project.id, script_version_id="scr_film",
        subtitle_version_id="sub_film", status=STATUS_CONFIRMED, provider="rules", model="rules-v1",
        variants=[ContentVariant("var_film", "标准", "clean", scenes)], selected_variant_index=0,
        total_duration_seconds=max(end for _, end in spans), error_code=None, created_at=now, updated_at=now,
        confirmed_at=now,
    ))
    session.flush()
    return project.id


def _accept_all_keyframes(session: Session, storage: ObjectStoragePublicService, project_id: str, scene_count: int) -> None:
    service = VideoKeyframeApplicationService(storage=storage)
    for index in range(scene_count):
        service.generate_candidate(session, project_id=project_id, scene_id=f"scene_{index + 1}", n=1)
        candidates = [
            item for item in service.list_candidates(session, project_id=project_id)
            if item.scene_id == f"scene_{index + 1}" and item.status == "ready"
        ]
        assert candidates, f"scene_{index + 1} 未产出可用关键帧"
        service.accept_candidate(session, project_id=project_id, keyframe_id=candidates[0].id)


class _SpyService(VideoPlanApplicationService):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.calls: list[tuple[int, float, int]] = []

    def _generate_film_clip(self, plan, call, refs, *, character_sheet=None):  # type: ignore[override]
        # 出镜人母版：父类会把它追加到参考图**最后**（media 顺序 = [各镜关键帧..., 母版]），
        # 这里把"是否带母版"也记下来，供测试断言编号与顺序。
        self.calls.append((call.order, call.duration_seconds, len(refs) + (1 if character_sheet else 0)))
        return super()._generate_film_clip(plan, call, refs, character_sheet=character_sheet)


def test_one_shot_single_call_when_total_under_limit(db_session: Session, object_storage: ObjectStoragePublicService) -> None:
    project_id = _seed(db_session, object_storage, spans=[(0, 5), (5, 10)], name="整片单次")
    _accept_all_keyframes(db_session, object_storage, project_id, 2)
    service = _SpyService(storage=object_storage)
    plan = service.create_plan(db_session, project_id=project_id, mode="product", template_id="clean", path="one_shot").plan
    video = service._create_one_shot_video(db_session, plan)
    assert service.calls == [(1, 10.0, 2)]
    assert video
    assert inspect_video_dimensions(video) == (1080, 1920)


def test_one_shot_splits_into_two_calls_and_concatenates(db_session: Session, object_storage: ObjectStoragePublicService) -> None:
    project_id = _seed(
        db_session, object_storage, spans=[(0, 3), (3, 6), (6, 13), (13, 18)], name="整片切分"
    )
    _accept_all_keyframes(db_session, object_storage, project_id, 4)
    service = _SpyService(storage=object_storage)
    plan = service.create_plan(db_session, project_id=project_id, mode="product", template_id="clean", path="one_shot").plan
    video = service._create_one_shot_video(db_session, plan)
    # 边界后移：两次调用各带 2 张参考图（原先第二次只带 1 张 → 供应商拒绝）
    assert service.calls == [(1, 6.0, 2), (2, 12.0, 2)]
    assert video
    assert inspect_video_dimensions(video) == (1080, 1920)