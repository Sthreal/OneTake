from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
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
from onetake_api.modules.video_plan.repository import VideoPlanRepository
from onetake_api.modules.video_plan.segment_service import VideoSegmentApplicationService
from onetake_api.modules.video_plan.service import VideoPlanApplicationService
from onetake_api.modules.voice.domain import VOICE_CONFIRMED, VoiceRun
from onetake_api.modules.voice.repository import VoiceRepository


class _FakeComposition:
    provider_name = "mock-video"

    def compose(self, _request):
        return b"final"


def _scene(order: int) -> ContentScene:
    start = float(order * 5)
    return ContentScene(
        scene_id=f"scene_{order}", order=order, purpose="展示", script_excerpt="文案",
        start_seconds=start, end_seconds=start + 5, shot_type="medium", prompt="商品展示",
        overlay_product=True, product_position="center", background_style="clean", template_id="clean",
        subtitle_segment_ids=[order + 1], qa_rules=[], visual_goal="卖点", subject_action="展示",
        camera_move="slow_push_in", product_mode="overlay", transition="fade",
    )


def _seed_video_plan(session: Session, storage: ObjectStoragePublicService, *, product_name: str):
    project = ProjectPublicService().create_project(session, product_name=product_name, product_note=None)
    now = datetime.now(UTC)
    image_key = f"projects/{project.id}/main.png"
    storage.put_bytes(object_key=image_key, content=b"image", mime_type="image/png")
    MainImageRepository().add(session, MainImageVersion("miv_seg", project.id, "ast_seg", "confirmed", "edt_seg", "mat_seg", image_key, None, 2000, 2000, 1000, 1000, 1000, 0.82, None, now, now, now, now))
    VoiceRepository().add(session, VoiceRun("voi_seg", project.id, "scr_seg", VOICE_CONFIRMED, True, True, "mock", "cosyvoice-v2", "female", "zh", 1.0, "测试文案。", f"projects/{project.id}/voice.wav", "audio/wav", 18.0, [], None, now, now, now, now))
    SubtitleRepository().add(session, SubtitleVersion("sub_seg", project.id, "scr_seg", "voi_seg", SUBTITLE_CONFIRMED, True, "zh", [{"index": 1, "text": "测试文案。", "start": 0, "end": 18}], f"projects/{project.id}/subtitle.srt", None, now, now, now, now))
    PipelinePublicService().mark_audio_subtitle_confirmed(session, project.id)
    scenes = [_scene(0), _scene(1), _scene(2)]
    content_plan = ContentPlan(
        id="cpl_seg", project_id=project.id, script_version_id="scr_seg", subtitle_version_id="sub_seg",
        status=STATUS_CONFIRMED, provider="rules", model="rules-v1",
        variants=[ContentVariant("var_seg", "标准", "clean", scenes)], selected_variant_index=0,
        total_duration_seconds=15.0, error_code=None, created_at=now, updated_at=now, confirmed_at=now,
    )
    ContentPlanRepository().add(session, content_plan)
    plan = VideoPlanApplicationService(storage=storage, composition=_FakeComposition()).create_plan(
        session, project_id=project.id, mode="product", template_id="clean"
    ).plan
    session.flush()
    return project.id, plan


def test_segment_list_empty_when_no_plan(client: TestClient) -> None:
    project = client.post("/api/v1/projects", json={"product_name": "无方案"}).json()["data"]
    response = client.get(f"/api/v1/projects/{project['project_id']}/video/segments")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "VIDEO_PLAN_NOT_FOUND"


def test_segment_materialization_from_content_plan(client: TestClient, db_session: Session, object_storage: ObjectStoragePublicService) -> None:
    project_id, plan = _seed_video_plan(db_session, object_storage, product_name="分段列")
    response = client.get(f"/api/v1/projects/{project_id}/video/segments")
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["plan_id"] == plan.id
    assert [seg["order_index"] for seg in body["segments"]] == [0, 1, 2]
    assert all(seg["status"] == "planned" for seg in body["segments"])
    assert all(seg["duration_seconds"] == 5.0 for seg in body["segments"])
    # 二次读取不应重复物化
    again = client.get(f"/api/v1/projects/{project_id}/video/segments").json()["data"]["segments"]
    assert len(again) == 3


def test_segment_accept_and_reject_via_api(client: TestClient, db_session: Session, object_storage: ObjectStoragePublicService) -> None:
    project_id, plan = _seed_video_plan(db_session, object_storage, product_name="分段收")
    segments = client.get(f"/api/v1/projects/{project_id}/video/segments").json()["data"]["segments"]
    assert len(segments) == 3
    first_id = segments[0]["segment_id"]
    # 手工注入一个候选以便 accept（生成在切片 3）
    from onetake_api.modules.video_plan.segment_domain import VideoSegmentCandidate
    from onetake_api.modules.video_plan.segment_repository import VideoSegmentCandidateRepository
    now = datetime.now(UTC)
    candidate = VideoSegmentCandidate(id="cand_api_1", segment_id=first_id, plan_id=plan.id, project_id=project_id, order_index=1, status="ready", provider="mock", anchor_source="scene_keyframe", created_at=now, video_object_key="projects/x/seg/0/c.mp4")
    VideoSegmentCandidateRepository().add(db_session, candidate)
    db_session.flush()

    accept = client.post(f"/api/v1/projects/{project_id}/video/segments/{first_id}/accept", json={"candidate_id": "cand_api_1"})
    assert accept.status_code == 200
    accepted_segments = accept.json()["data"]["segments"]
    assert accepted_segments[0]["status"] == "accepted"
    assert accepted_segments[0]["accepted_candidate_id"] == "cand_api_1"

    reject = client.post(f"/api/v1/projects/{project_id}/video/segments/{first_id}/reject")
    assert reject.status_code == 200
    rejected_segments = reject.json()["data"]["segments"]
    assert rejected_segments[0]["status"] == "planned"
    assert rejected_segments[0]["accepted_candidate_id"] is None
