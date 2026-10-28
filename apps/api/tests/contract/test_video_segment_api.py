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


def test_segment_exposes_preview_and_thumbnail_urls(
    client: TestClient, db_session: Session, object_storage: ObjectStoragePublicService
) -> None:
    """S2：段级 preview_url / thumbnail_url 取自已采纳候选（时间线卡片直接可用）。"""
    project_id, plan = _seed_video_plan(db_session, object_storage, product_name="分段预览")
    segments = client.get(f"/api/v1/projects/{project_id}/video/segments").json()["data"]["segments"]
    first_id = segments[0]["segment_id"]
    # 还没采纳任何候选 → 两个字段都是 None（不伪造 URL）
    assert segments[0]["preview_url"] is None
    assert segments[0]["thumbnail_url"] is None

    from onetake_api.modules.video_plan.segment_domain import VideoSegmentCandidate
    from onetake_api.modules.video_plan.segment_repository import VideoSegmentCandidateRepository

    now = datetime.now(UTC)
    candidate = VideoSegmentCandidate(
        id="cand_prev_1", segment_id=first_id, plan_id=plan.id, project_id=project_id, order_index=1,
        status="ready", provider="mock", anchor_source="scene_keyframe", created_at=now,
        video_object_key="projects/x/seg/0/v.mp4", head_frame_object_key="projects/x/seg/0/head.png",
    )
    VideoSegmentCandidateRepository().add(db_session, candidate)
    db_session.flush()

    accept = client.post(
        f"/api/v1/projects/{project_id}/video/segments/{first_id}/accept", json={"candidate_id": "cand_prev_1"}
    )
    assert accept.status_code == 200
    accepted = accept.json()["data"]["segments"][0]
    assert accepted["accepted_candidate_id"] == "cand_prev_1"
    assert accepted["preview_url"] and "v.mp4" in accepted["preview_url"]
    assert accepted["thumbnail_url"] and "head.png" in accepted["thumbnail_url"]


def test_batch_step_param_rejects_out_of_range(
    client: TestClient, db_session: Session, object_storage: ObjectStoragePublicService
) -> None:
    """S2：stop_after_segments 取值域 1..50，越界在 schema 层被拒（不静默当默认值）。"""
    project_id, _plan = _seed_video_plan(db_session, object_storage, product_name="分步步进")
    assert client.post(f"/api/v1/projects/{project_id}/video/batch?stop_after_segments=0").status_code == 422
    assert client.post(f"/api/v1/projects/{project_id}/video/batch?stop_after_segments=51").status_code == 422


def test_segment_exposes_quality_metrics(
    client: TestClient, db_session: Session, object_storage: ObjectStoragePublicService
) -> None:
    """S6：段级质量指标（关键帧质检 + 时长偏差 + 症状）随段返回；没有的部分就是 None。"""
    project_id, plan = _seed_video_plan(db_session, object_storage, product_name="分段质量")
    segments = client.get(f"/api/v1/projects/{project_id}/video/segments").json()["data"]["segments"]
    first = segments[0]
    # 尚未采纳任何东西 → 各项为 None（不伪造）
    assert first["quality"]["product_match"] is None
    assert first["quality"]["duration_delta_seconds"] is None

    from datetime import UTC, datetime as _dt

    from onetake_api.modules.video_plan.keyframe_domain import KEYFRAME_ACCEPTED, VideoKeyframeCandidate
    from onetake_api.modules.video_plan.keyframe_repository import VideoKeyframeCandidateRepository
    from onetake_api.modules.video_plan.segment_domain import VideoSegmentCandidate
    from onetake_api.modules.video_plan.segment_repository import VideoSegmentCandidateRepository

    now = _dt.now(UTC)
    VideoKeyframeCandidateRepository().add(db_session, VideoKeyframeCandidate(
        id="kfc_quality", project_id=project_id, content_plan_id="cpl_seg", scene_id=first["scene_id"],
        order_index=1, mode="integrated", status=KEYFRAME_ACCEPTED, provider="test", created_at=now,
        image_object_key="projects/x/kf.png", width=1080, height=1920, product_match=0.88,
        text_intact=True, fallback="pixel_lock",
    ))
    VideoSegmentCandidateRepository().add(db_session, VideoSegmentCandidate(
        id="cand_quality", segment_id=first["segment_id"], plan_id=plan.id, project_id=project_id,
        order_index=1, status="ready", provider="mock", anchor_source="integrated_keyframe", created_at=now,
        video_object_key="projects/x/seg/0/v.mp4", duration_seconds=4.5, symptom="text_blurry",
    ))
    db_session.flush()
    accept = client.post(
        f"/api/v1/projects/{project_id}/video/segments/{first['segment_id']}/accept",
        json={"candidate_id": "cand_quality"},
    )
    assert accept.status_code == 200
    quality = accept.json()["data"]["segments"][0]["quality"]
    assert quality["product_match"] == 0.88
    assert quality["text_intact"] is True
    assert quality["keyframe_fallback"] == "pixel_lock"
    assert quality["duration_delta_seconds"] == -0.5      # 4.5s 实际 vs 5.0s 计划
    assert quality["symptom"] == "text_blurry"


def test_plan_settings_patch_switches_free_knobs(
    client: TestClient, db_session: Session, object_storage: ObjectStoragePublicService
) -> None:
    """S6：导演模式的免费旋钮 —— PATCH 生效、非法值 422、空 body 不变、默认值即历史行为。"""
    project_id, _plan = _seed_video_plan(db_session, object_storage, product_name="免费旋钮")
    url = f"/api/v1/projects/{project_id}/video-plan"

    current = client.get(f"/api/v1/projects/{project_id}/video").json()["data"]["plan"]
    assert current["seam_mode"] == "pin"          # 默认 = S6 之前的行为
    assert current["motion_realism"] == "auto"    # 新项目 auto（老项目由迁移 0024 写 off）

    patched = client.patch(url, json={"seam_mode": "tail", "motion_realism": "constraints"})
    assert patched.status_code == 200
    assert patched.json()["data"]["plan"]["seam_mode"] == "tail"
    assert patched.json()["data"]["plan"]["motion_realism"] == "constraints"

    assert client.patch(url, json={"seam_mode": "off"}).status_code == 200
    assert client.patch(url, json={}).status_code == 200
    assert client.patch(url, json={"seam_mode": "bogus"}).status_code == 422
    assert client.patch(url, json={"motion_realism": "bogus"}).status_code == 422


def test_repairs_and_preflight_without_plan_return_404_not_500(client: TestClient) -> None:
    """没有视频方案时，两个只读端点必须给**明确 404**，不是 500。

    2026-10-16 用户实测：新项目刚跑完自动链（分镜 ready、还没建方案）时，分镜页每刷一次就吃两个 500
    （`'NoneType' object has no attribute 'id'` / `'path'`）—— 只读端点不能假设方案存在。
    """
    project = client.post("/api/v1/projects", json={"product_name": "还没方案"}).json()["data"]
    pid = project["project_id"]
    for path in (
        f"/api/v1/projects/{pid}/video/repairs",
        f"/api/v1/projects/{pid}/video/model-preflight",
    ):
        response = client.get(path)
        assert response.status_code == 404, (path, response.status_code, response.text)
        assert response.json()["error"]["code"] == "VIDEO_PLAN_NOT_FOUND", (path, response.text)


def test_video_repairs_and_model_preflight_endpoints(
    client: TestClient, db_session: Session, object_storage: ObjectStoragePublicService
) -> None:
    """S6：两个只读端点 —— 修复计划（只翻译不执行）与模型能力预检（只报事实）。"""
    from dataclasses import replace as _replace

    from onetake_api.modules.video_plan.repository import VideoPlanRepository

    project_id, plan = _seed_video_plan(db_session, object_storage, product_name="修复与预检")

    empty = client.get(f"/api/v1/projects/{project_id}/video/repairs").json()["data"]
    assert empty["actions"] == []
    assert empty["gate_status"] is None

    report = {
        "status": "warn",
        "checks": [{"id": "silence", "level": "warn", "label": "静音", "message": "1 段静音", "at_seconds": []}],
    }
    VideoPlanRepository().update(db_session, _replace(plan, gate_report=report))
    db_session.flush()

    body = client.get(f"/api/v1/projects/{project_id}/video/repairs").json()["data"]
    assert body["gate_status"] == "warn"
    assert len(body["actions"]) == 1
    assert body["actions"][0]["action"] == "recompose"
    assert body["actions"][0]["execute_endpoint"].endswith("/compose")

    preflight = client.get(
        f"/api/v1/projects/{project_id}/video/model-preflight?path=segmented&seam_mode=pin"
    ).json()["data"]
    assert preflight["model_kind"] == "wan-kf2v"
    assert preflight["capabilities"]["last_frame"] is True
    assert any(item["code"] == "capabilities" for item in preflight["checks"])
    assert client.get(f"/api/v1/projects/{project_id}/video/model-preflight?seam_mode=bogus").status_code == 422


def test_keyframes_expose_prompt_warning_field(
    client: TestClient, db_session: Session, object_storage: ObjectStoragePublicService
) -> None:
    """S4a：关键帧接口带 `prompt_warning`（规则本身由 S5 单测钉住，这里证明字段真的接通）。"""
    project_id, _plan = _seed_video_plan(db_session, object_storage, product_name="静态告警")
    body = client.get(f"/api/v1/projects/{project_id}/video/keyframes").json()["data"]
    assert body["keyframes"], "应当有分镜槽位"
    assert "prompt_warning" in body["keyframes"][0]
    assert body["keyframes"][0]["prompt_warning"] is None      # 测试分镜的提示词里没有时序词


def test_scene_camera_allows_editing_after_confirmation(
    client: TestClient, db_session: Session, object_storage: ObjectStoragePublicService
) -> None:
    """S4-②：批量 PATCH 在方案已确认后仍然拒绝（409），但**逐镜运镜**允许改。

    为什么允许：运镜是生成参数（进 i2v 运动提示词），不改镜数/时长/文案/商品位，也不改费用预估。
    生效时机是"下一次生成该镜" —— 已生成的候选不动。
    """
    project_id, _plan = _seed_video_plan(db_session, object_storage, product_name="逐镜运镜")
    body = client.get(f"/api/v1/projects/{project_id}/content-plan").json()["data"]
    assert body["status"] == "confirmed"
    index = body["selected_variant_index"]
    scenes = body["variants"][index]["scenes"]

    # 既有语义不动：批量改分镜在已确认后仍被拒
    assert client.patch(f"/api/v1/projects/{project_id}/content-plan", json={"scenes": scenes}).status_code == 409

    scene_id = scenes[0]["scene_id"]
    ok = client.patch(
        f"/api/v1/projects/{project_id}/content-plan/scene/{scene_id}/camera",
        json={"camera_move": "从低角度缓慢环绕瓶身"},
    )
    assert ok.status_code == 200
    assert ok.json()["data"]["variants"][index]["scenes"][0]["camera_move"] == "从低角度缓慢环绕瓶身"

    missing = client.patch(
        f"/api/v1/projects/{project_id}/content-plan/scene/scene_unknown/camera",
        json={"camera_move": "slow_push_in"},
    )
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "CONTENT_PLAN_VALIDATION_ERROR"


def test_segment_seam_changes_the_estimate(
    client: TestClient, db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    """S4-③（同时修 S6 遗留 bug）：段级接缝改变 kf2v/i2v 条数 → **费用预估必须随变**。

    为什么这条最关键：费用审批绑定 `payload_hash`（含整份预估）。预估若不读接缝，
    改接缝就不会改哈希 → 旧批准继续有效，而**实际调用与批准的那份预估不一致**。
    """
    # 本用例必须走**分段**路径、且按**真实计价**口径（mock 模式下预估直接短路成 0 次调用、
    # 没有 kf2v/i2v 之分），所以前置自带，不依赖环境。
    monkeypatch.setenv("GENERATION_PATH_DEFAULT", "segmented")
    monkeypatch.setenv("MOCK_PROVIDERS", "false")
    monkeypatch.setenv("WAN_I2V_PROVIDER", "real")
    monkeypatch.setenv("VIDEO_KF2V_ENABLED", "true")
    from onetake_api.config import get_settings

    get_settings.cache_clear()
    project_id, plan = _seed_video_plan(db_session, object_storage, product_name="段级接缝预估")
    base = client.get(f"/api/v1/projects/{project_id}/video-plan/{plan.id}/estimate").json()["data"]
    assert base["path"] == "segmented"
    assert base["kf2v_clips"] > 0, "mock 路径下首尾帧档可用，基线应当有 kf2v"
    base_kf2v, base_i2v = base["kf2v_clips"], base["i2v_clips"]

    segments = client.get(f"/api/v1/projects/{project_id}/video/segments").json()["data"]["segments"]
    target = segments[0]["segment_id"]

    patched = client.patch(
        f"/api/v1/projects/{project_id}/video/segments/{target}/seam", json={"seam_mode": "off"}
    )
    assert patched.status_code == 200
    assert patched.json()["data"]["segments"][0]["seam_mode"] == "off"

    after = client.get(f"/api/v1/projects/{project_id}/video-plan/{plan.id}/estimate").json()["data"]
    assert after["kf2v_clips"] == base_kf2v - 1
    assert after["i2v_clips"] == base_i2v + 1

    cleared = client.patch(
        f"/api/v1/projects/{project_id}/video/segments/{target}/seam", json={"seam_mode": None}
    )
    assert cleared.status_code == 200
    assert cleared.json()["data"]["segments"][0]["seam_mode"] is None
    restored = client.get(f"/api/v1/projects/{project_id}/video-plan/{plan.id}/estimate").json()["data"]
    assert (restored["kf2v_clips"], restored["i2v_clips"]) == (base_kf2v, base_i2v)

    assert client.patch(
        f"/api/v1/projects/{project_id}/video/segments/{target}/seam", json={"seam_mode": "bogus"}
    ).status_code == 422


def test_compose_options_expose_the_single_source_of_truth(
    client: TestClient, db_session: Session, object_storage: ObjectStoragePublicService
) -> None:
    """S4-④a：合成旋钮的清单由后端给（前端下拉不自己写一份）。"""
    project_id, _plan = _seed_video_plan(db_session, object_storage, product_name="合成旋钮清单")
    body = client.get(f"/api/v1/projects/{project_id}/video/compose-options").json()["data"]
    assert [item["id"] for item in body["caption_styles"]] == ["standard", "bold", "minimal", "karaoke"]
    assert all(item["label"] for item in body["caption_styles"])
    assert (body["bgm"]["gain_db_min"], body["bgm"]["gain_db_max"]) == (-40.0, 0.0)


def test_plan_compose_overrides_can_be_set_and_are_validated(
    client: TestClient, db_session: Session, object_storage: ObjectStoragePublicService
) -> None:
    """S4-④a：方案级字幕样式 / BGM 开关 / BGM 强度 —— 可设、可校验、默认跟全局。"""
    project_id, _plan = _seed_video_plan(db_session, object_storage, product_name="合成旋钮")
    url = f"/api/v1/projects/{project_id}/video-plan"

    current = client.get(f"/api/v1/projects/{project_id}/video").json()["data"]["plan"]
    assert current["caption_style"] is None          # None = 跟全局配置
    assert current["bgm_enabled"] is None
    assert current["bgm_gain_db"] is None

    ok = client.patch(url, json={"caption_style": "karaoke", "bgm_enabled": True, "bgm_gain_db": -8.0})
    assert ok.status_code == 200
    plan = ok.json()["data"]["plan"]
    assert plan["caption_style"] == "karaoke"
    assert plan["bgm_enabled"] is True
    assert plan["bgm_gain_db"] == -8.0

    # 未知字幕样式：**显式报错**（不静默回落成默认档 —— 否则就是「选了没生效」）
    assert client.patch(url, json={"caption_style": "not-a-style"}).status_code == 422
    # BGM 强度越界：schema 层拦住
    assert client.patch(url, json={"bgm_gain_db": -80}).status_code == 422

    # 明确关掉 BGM 也要能被表达（False 不能被当成"没设"）
    off = client.patch(url, json={"bgm_enabled": False})
    assert off.status_code == 200
    assert off.json()["data"]["plan"]["bgm_enabled"] is False

    # **「没提」与「显式 null」必须区分**：null = 清除覆盖（回跟随全局），没提 = 不动
    cleared = client.patch(url, json={"caption_style": None, "bgm_enabled": None, "bgm_gain_db": None})
    assert cleared.status_code == 200
    cleared_plan = cleared.json()["data"]["plan"]
    assert cleared_plan["caption_style"] is None
    assert cleared_plan["bgm_enabled"] is None
    assert cleared_plan["bgm_gain_db"] is None

    client.patch(url, json={"caption_style": "bold", "bgm_gain_db": -10.0})
    partial = client.patch(url, json={"bgm_enabled": False}).json()["data"]["plan"]
    assert partial["bgm_enabled"] is False
    assert partial["caption_style"] == "bold"      # 本次没提 → 不动
    assert partial["bgm_gain_db"] == -10.0         # 本次没提 → 不动
