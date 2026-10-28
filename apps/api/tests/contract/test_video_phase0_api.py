"""Phase 0 契约测试：运动字段透出、关键帧、交付门、合规、生成路径。

这些接口在 Phase 0 只冻结结构：
- 读接口返回真实（可能是空）状态，不伪造数据
- 写接口（关键帧生成/确认、症状返修、警告确认）返回 501 FEATURE_NOT_IMPLEMENTED
"""
from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
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
from onetake_api.modules.video_plan.service import VideoPlanApplicationService
from onetake_api.modules.voice.domain import VOICE_CONFIRMED, VoiceRun
from onetake_api.modules.voice.repository import VoiceRepository


def _main_image_png(size: int = 512) -> bytes:
    """主图必须是真实 PNG：关键帧生成会把它当参考图读进 PIL。"""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((40, 90, size - 40, size - 70), radius=40, fill=(196, 42, 42, 255))
    draw.rectangle((70, 140, size - 70, 175), fill=(255, 255, 255, 255))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


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


def _seed_ready_project(session: Session, storage: ObjectStoragePublicService, *, product_name: str) -> str:
    """把项目推进到"分镜已确认"，用于测试关键帧与方案创建。"""
    project = ProjectPublicService().create_project(session, product_name=product_name, product_note=None)
    now = datetime.now(UTC)
    image_key = f"projects/{project.id}/main.png"
    storage.put_bytes(object_key=image_key, content=_main_image_png(), mime_type="image/png")
    MainImageRepository().add(session, MainImageVersion("miv_p0", project.id, "ast_p0", "confirmed", "edt_p0", "mat_p0", image_key, None, 2000, 2000, 1000, 1000, 1000, 0.82, None, now, now, now, now))
    VoiceRepository().add(session, VoiceRun("voi_p0", project.id, "scr_p0", VOICE_CONFIRMED, True, True, "mock", "cosyvoice-v2", "female", "zh", 1.0, "测试文案。", f"projects/{project.id}/voice.wav", "audio/wav", 15.0, [], None, now, now, now, now))
    SubtitleRepository().add(session, SubtitleVersion("sub_p0", project.id, "scr_p0", "voi_p0", SUBTITLE_CONFIRMED, True, "zh", [{"index": 1, "text": "测试文案。", "start": 0, "end": 15}], f"projects/{project.id}/subtitle.srt", None, now, now, now, now))
    PipelinePublicService().mark_audio_subtitle_confirmed(session, project.id)
    ContentPlanRepository().add(session, ContentPlan(
        id="cpl_p0", project_id=project.id, script_version_id="scr_p0", subtitle_version_id="sub_p0",
        status=STATUS_CONFIRMED, provider="rules", model="rules-v1",
        variants=[ContentVariant("var_p0", "标准", "clean", [_scene(0), _scene(1)])], selected_variant_index=0,
        total_duration_seconds=10.0, error_code=None, created_at=now, updated_at=now, confirmed_at=now,
    ))
    session.flush()
    return project.id


def _seed_video_plan(session: Session, storage: ObjectStoragePublicService, *, product_name: str):
    """在"分镜已确认"的基础上创建视频方案，供分段/返修用例使用。"""
    project_id = _seed_ready_project(session, storage, product_name=product_name)
    plan = VideoPlanApplicationService(storage=storage, composition=_FakeComposition()).create_plan(
        session, project_id=project_id, mode="product", template_id="clean"
    ).plan
    session.flush()
    return project_id, plan


def test_content_plan_options_expose_motion_fields(client: TestClient) -> None:
    project = client.post("/api/v1/projects", json={"product_name": "运动选项"}).json()["data"]
    response = client.get(f"/api/v1/projects/{project['project_id']}/content-plan/options")
    assert response.status_code == 200
    data = response.json()["data"]
    assert "slow_push_in" in [item["id"] for item in data["camera_moves"]]
    assert "fade" in [item["id"] for item in data["transitions"]]
    assert {"absent", "overlay", "closeup", "integrated"} <= {item["id"] for item in data["product_modes"]}


def test_video_plan_rejects_unknown_path(client: TestClient) -> None:
    project = client.post("/api/v1/projects", json={"product_name": "非法路径"}).json()["data"]
    response = client.post(
        f"/api/v1/projects/{project['project_id']}/video-plan",
        json={"mode": "product", "template_id": "clean", "path": "turbo"},
    )
    assert response.status_code == 422


def test_keyframes_empty_without_content_plan(client: TestClient) -> None:
    project = client.post("/api/v1/projects", json={"product_name": "无分镜"}).json()["data"]
    response = client.get(f"/api/v1/projects/{project['project_id']}/video/keyframes")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["keyframes"] == []
    # Phase 1 上线前必须明确标记不可生成，前端据此禁用入口
    assert data["generation_available"] is False


def test_keyframes_list_scenes_from_confirmed_plan(
    client: TestClient, db_session: Session, object_storage: ObjectStoragePublicService
) -> None:
    project_id = _seed_ready_project(db_session, object_storage, product_name="关键帧列")
    response = client.get(f"/api/v1/projects/{project_id}/video/keyframes")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["content_plan_id"] == "cpl_p0"
    assert [slot["scene_id"] for slot in data["keyframes"]] == ["scene_0", "scene_1"]
    assert all(slot["candidates"] == [] and slot["accepted"] is None for slot in data["keyframes"])


def test_keyframe_generate_and_accept_flow(
    client: TestClient, db_session: Session, object_storage: ObjectStoragePublicService
) -> None:
    """Phase 1：mock 模式下"生成候选 → 质检通过 → 采纳"端到端可用，且不产生付费调用。"""
    project_id = _seed_ready_project(db_session, object_storage, product_name="关键帧生成")
    generated = client.post(
        f"/api/v1/projects/{project_id}/video/keyframes/scene_0/candidates", json={"n": 1}
    )
    assert generated.status_code == 201
    state = generated.json()["data"]
    assert state["generation_available"] is True
    slot = next(item for item in state["keyframes"] if item["scene_id"] == "scene_0")
    assert len(slot["candidates"]) == 1
    candidate = slot["candidates"][0]
    assert candidate["mode"] == "integrated"
    assert candidate["status"] == "ready"
    assert candidate["image_url"]
    assert candidate["product_match"] is not None
    assert slot["accepted"] is None

    accepted = client.post(
        f"/api/v1/projects/{project_id}/video/keyframes/scene_0/accept",
        json={"keyframe_id": candidate["keyframe_id"]},
    )
    assert accepted.status_code == 200
    slot_after = next(item for item in accepted.json()["data"]["keyframes"] if item["scene_id"] == "scene_0")
    assert slot_after["accepted"]["keyframe_id"] == candidate["keyframe_id"]
    assert slot_after["accepted"]["status"] == "accepted"


def test_keyframe_generation_requires_confirmed_content_plan(client: TestClient) -> None:
    project = client.post("/api/v1/projects", json={"product_name": "未确认分镜"}).json()["data"]
    response = client.post(f"/api/v1/projects/{project['project_id']}/video/keyframes/scene_0/candidates", json={})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "KEYFRAME_CONFLICT"


def _accept_keyframe(client: TestClient, project_id: str, *, scene_id: str) -> None:
    """M4-03 提交 2 起：商品段必须有已采用的入画关键帧，否则分段生成会明确报错。"""
    generated = client.post(f"/api/v1/projects/{project_id}/video/keyframes/{scene_id}/candidates", json={"n": 1})
    assert generated.status_code == 201, generated.text
    slot = next(item for item in generated.json()["data"]["keyframes"] if item["scene_id"] == scene_id)
    accepted = client.post(
        f"/api/v1/projects/{project_id}/video/keyframes/{scene_id}/accept",
        json={"keyframe_id": slot["candidates"][0]["keyframe_id"]},
    )
    assert accepted.status_code == 200, accepted.text

def test_retake_records_single_variable_symptom(
    client: TestClient, db_session: Session, object_storage: ObjectStoragePublicService
) -> None:
    """Phase 2：症状式返修生成一个新候选，并把它只改了什么记录下来。"""
    project_id, _plan = _seed_video_plan(db_session, object_storage, product_name="症状返修")
    # M4-03 提交 2 起：商品段必须有已采用的入画关键帧（背景回退已废弃）
    _accept_keyframe(client, project_id, scene_id="scene_0")
    segments = client.get(f"/api/v1/projects/{project_id}/video/segments").json()["data"]["segments"]
    assert segments
    segment_id = segments[0]["segment_id"]

    normal = client.post(f"/api/v1/projects/{project_id}/video/segments/{segment_id}/candidates", json={})
    assert normal.status_code == 201
    assert normal.json()["data"]["segments"][0]["candidates"][-1]["symptom"] is None

    retake = client.post(
        f"/api/v1/projects/{project_id}/video/segments/{segment_id}/retake", json={"symptom": "text_blurry"}
    )
    assert retake.status_code == 201
    latest = retake.json()["data"]["segments"][0]["candidates"][-1]
    assert latest["symptom"] == "text_blurry"
    assert latest["status"] == "ready"


def test_segment_uses_accepted_keyframe_as_anchor(
    client: TestClient, db_session: Session, object_storage: ObjectStoragePublicService
) -> None:
    """Phase 1 → Phase 2 的关键接线：已采用的关键帧必须真的被分段生成当作首帧锚点。"""
    project_id, _plan = _seed_video_plan(db_session, object_storage, product_name="关键帧锚点")
    generated = client.post(f"/api/v1/projects/{project_id}/video/keyframes/scene_0/candidates", json={"n": 1})
    slot = generated.json()["data"]["keyframes"][0]
    assert slot["scene_id"] == "scene_0"
    keyframe_id = slot["candidates"][0]["keyframe_id"]
    accepted = client.post(
        f"/api/v1/projects/{project_id}/video/keyframes/scene_0/accept", json={"keyframe_id": keyframe_id}
    )
    assert accepted.status_code == 200

    segments = client.get(f"/api/v1/projects/{project_id}/video/segments").json()["data"]["segments"]
    segment = next(item for item in segments if item["scene_id"] == "scene_0")
    candidate = client.post(
        f"/api/v1/projects/{project_id}/video/segments/{segment['segment_id']}/candidates", json={}
    )
    assert candidate.status_code == 201
    latest = next(
        item for item in candidate.json()["data"]["segments"] if item["scene_id"] == "scene_0"
    )["candidates"][-1]
    assert latest["anchor_source"] == "integrated_keyframe"

def test_retake_rejects_unknown_symptom(
    client: TestClient, db_session: Session, object_storage: ObjectStoragePublicService
) -> None:
    project_id, _plan = _seed_video_plan(db_session, object_storage, product_name="未知症状")
    bad = client.post(f"/api/v1/projects/{project_id}/video/segments/seg_unknown/retake", json={"symptom": "unknown"})
    assert bad.status_code == 422


def test_gate_ack_rejects_unknown_check(client: TestClient) -> None:
    """Phase 5：确认接口只能确认"当前确实是警告"的条目，未知/非警告一律拒绝。"""
    project = client.post("/api/v1/projects", json={"product_name": "确认校验"}).json()["data"]
    response = client.post(
        f"/api/v1/projects/{project['project_id']}/video/gate/ack", json={"check_ids": ["not_a_check"]}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VIDEO_VALIDATION_ERROR"


def test_gate_ack_unlocks_download(client: TestClient) -> None:
    """警告确认后 download_allowed 才为真（未确认时不允许下载）。"""
    project = client.post("/api/v1/projects", json={"product_name": "确认解锁"}).json()["data"]
    project_id = project["project_id"]
    before = client.get(f"/api/v1/projects/{project_id}/video/gate").json()["data"]
    assert before["status"] == "warn"
    assert before["download_allowed"] is False

    ack = client.post(
        f"/api/v1/projects/{project_id}/video/gate/ack",
        json={"check_ids": [before["checks"][0]["id"]]},
    )
    assert ack.status_code == 200
    data = ack.json()["data"]
    assert before["checks"][0]["id"] in data["acknowledged"]
    assert data["download_allowed"] is True


def test_gate_warns_without_quality_report(client: TestClient) -> None:
    project = client.post("/api/v1/projects", json={"product_name": "交付门"}).json()["data"]
    response = client.get(f"/api/v1/projects/{project['project_id']}/video/gate")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "warn"
    assert [check["id"] for check in data["checks"]] == ["quality_report"]
    assert data["contact_sheet_url"] is None



def test_compliance_evaluates_rules_and_label_config(client: TestClient) -> None:
    """Phase 5：合规报告从"未评估占位"变成真评估（词表已加载、标识配置可见）。"""
    project = client.post("/api/v1/projects", json={"product_name": "合规"}).json()["data"]
    response = client.get(f"/api/v1/projects/{project['project_id']}/compliance")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["evaluated"] is True
    assert data["rules_version"].startswith("2026-")
    assert data["aigc_label_enabled"] is True
    assert data["aigc_label_source"] == "local"
    # 没有文案时不应凭空报命中
    assert data["banned_words"] == []
    assert data["platform_warnings"] == []


def test_video_plan_accepts_explicit_path_and_defaults_to_segmented(
    client: TestClient, db_session: Session, object_storage: ObjectStoragePublicService
) -> None:
    project_id = _seed_ready_project(db_session, object_storage, product_name="生成路径")
    # 不传 path：走服务端默认（同时在验证 MCP 等旧调用方的兼容性）
    default_plan = client.post(f"/api/v1/projects/{project_id}/video-plan", json={"mode": "product", "template_id": "clean"})
    assert default_plan.status_code == 201
    assert default_plan.json()["data"]["plan"]["path"] == "segmented"
    # 显式传 path：原样落到方案上
    explicit = client.post(
        f"/api/v1/projects/{project_id}/video-plan",
        json={"mode": "product", "template_id": "clean", "path": "one_shot"},
    )
    assert explicit.status_code == 201
    explicit_plan = explicit.json()["data"]["plan"]
    assert explicit_plan["path"] == "one_shot"


def test_estimate_exposes_phase0_fields(
    client: TestClient, db_session: Session, object_storage: ObjectStoragePublicService
) -> None:
    project_id = _seed_ready_project(db_session, object_storage, product_name="估算字段")
    created = client.post(f"/api/v1/projects/{project_id}/video-plan", json={"mode": "product", "template_id": "clean"})
    plan_id = created.json()["data"]["plan"]["plan_id"]
    response = client.get(f"/api/v1/projects/{project_id}/video-plan/{plan_id}/estimate")
    assert response.status_code == 200
    data = response.json()["data"]
    for key in ("path", "keyframe_calls", "keyframe_images", "i2v_clips", "kf2v_clips", "r2v_calls", "r2v_seconds", "composition"):
        assert key in data, key
    assert data["path"] == "segmented"