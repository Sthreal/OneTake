"""G2：本地合成端到端（mock 关键帧 + local 合成 + 完整 job 流 + 交付门确认）。

这是目前唯一没有自动化覆盖的组合：`COMPOSITION_PROVIDER=local` + 完整 `process_job`。
只验 4 件事（见 docs/收尾总方案.md §4 G2），不做生产代码改动。
"""
from __future__ import annotations

import wave
from datetime import UTC, datetime
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy.orm import Session

from onetake_api.integrations.media.local_composer import LocalCompositionAdapter
from onetake_api.integrations.media.video_utils import inspect_video_dimensions
from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.modules.content_plan.domain import STATUS_CONFIRMED, ContentPlan, ContentScene, ContentVariant
from onetake_api.modules.content_plan.repository import ContentPlanRepository
from onetake_api.modules.job.public import JobPublicService
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

WIDTH, HEIGHT, FPS = 1080, 1920, 30
DURATION = 18.0


class _FakeQueue:
    def enqueue(self, *_args, **_kwargs) -> None:
        return None


def _product_png(size: int = 512) -> bytes:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((40, 90, size - 40, size - 70), radius=40, fill=(196, 42, 42, 255))
    draw.rectangle((70, 140, size - 70, 175), fill=(255, 255, 255, 255))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _silent_wav(seconds: float = DURATION) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(48000)
        handle.writeframes(b"\x00\x00" * int(48000 * seconds))
    return buffer.getvalue()


def _srt() -> bytes:
    return "1\n00:00:00,000 --> 00:00:06,000\n测试字幕一\n\n2\n00:00:06,000 --> 00:00:12,000\n测试字幕二\n".encode("utf-8")


def _scene(order: int, start: float, end: float) -> ContentScene:
    return ContentScene(
        scene_id=f"scene_{order}", order=order, purpose="展示", script_excerpt=f"第{order}句台词",
        start_seconds=start, end_seconds=end, shot_type="medium", prompt="",
        overlay_product=True, product_position="center", background_style="clean", template_id="clean",
        subtitle_segment_ids=[order], qa_rules=[], visual_goal="product_reveal", subject_action="展示商品",
        camera_move="push_in", product_mode="integrated", transition="fade",
    )


def _seed_project(session: Session, storage: ObjectStoragePublicService, *, name: str) -> str:
    project = ProjectPublicService().create_project(session, product_name=name, product_note=None)
    now = datetime.now(UTC)
    image_key = f"projects/{project.id}/main.png"
    voice_key = f"projects/{project.id}/voice.wav"
    srt_key = f"projects/{project.id}/subtitle.srt"
    storage.put_bytes(object_key=image_key, content=_product_png(), mime_type="image/png")
    storage.put_bytes(object_key=voice_key, content=_silent_wav(), mime_type="audio/wav")
    storage.put_bytes(object_key=srt_key, content=_srt(), mime_type="application/x-subrip")
    MainImageRepository().add(session, MainImageVersion(
        "miv_local", project.id, "ast_local", "confirmed", "edt_local", "mat_local", image_key, None,
        2000, 2000, 1000, 1000, 1000, 0.82, None, now, now, now, now,
    ))
    VoiceRepository().add(session, VoiceRun(
        "voi_local", project.id, "scr_local", VOICE_CONFIRMED, True, True, "mock", "cosyvoice-v2",
        "female", "zh", 1.0, "测试文案。", voice_key, "audio/wav", DURATION, [], None, now, now, now, now,
    ))
    SubtitleRepository().add(session, SubtitleVersion(
        "sub_local", project.id, "scr_local", "voi_local", SUBTITLE_CONFIRMED, True, "zh",
        [{"index": 1, "text": "测试字幕一", "start": 0, "end": 6}, {"index": 2, "text": "测试字幕二", "start": 6, "end": 12}],
        srt_key, None, now, now, now, now,
    ))
    PipelinePublicService().mark_audio_subtitle_confirmed(session, project.id)
    ContentPlanRepository().add(session, ContentPlan(
        id="cpl_local", project_id=project.id, script_version_id="scr_local", subtitle_version_id="sub_local",
        status=STATUS_CONFIRMED, provider="rules", model="rules-v1",
        variants=[ContentVariant("var_local", "标准", "clean", [_scene(1, 0.0, 9.0), _scene(2, 9.0, 18.0)])],
        selected_variant_index=0, total_duration_seconds=DURATION, error_code=None,
        created_at=now, updated_at=now, confirmed_at=now,
    ))
    session.flush()
    return project.id


def _accept_all_keyframes(session: Session, storage: ObjectStoragePublicService, project_id: str) -> None:
    service = VideoKeyframeApplicationService(storage=storage)
    for scene_id in ("scene_1", "scene_2"):
        service.generate_candidate(session, project_id=project_id, scene_id=scene_id, n=1)
        ready = [
            item for item in service.list_candidates(session, project_id=project_id)
            if item.scene_id == scene_id and item.status == "ready"
        ]
        assert ready, f"{scene_id} 未产出可用关键帧"
        service.accept_candidate(session, project_id=project_id, keyframe_id=ready[0].id)


def test_local_composition_end_to_end(
    client: TestClient,
    db_session: Session,
    object_storage: ObjectStoragePublicService,
    monkeypatch,
) -> None:
    monkeypatch.setattr("onetake_api.modules.video_plan.service.get_queue", lambda _name: _FakeQueue())
    project_id = _seed_project(db_session, object_storage, name="本地合成端到端")
    _accept_all_keyframes(db_session, object_storage, project_id)

    # content_qa 走默认的 ContentQaPublicService（内部即 RuleContentQaAdapter，零付费调用）
    service = VideoPlanApplicationService(
        storage=object_storage,
        composition=LocalCompositionAdapter(),
    )
    plan = service.create_plan(db_session, project_id=project_id, mode="product", template_id="clean").plan
    assert plan is not None
    service.request_video(db_session, project_id)
    job = JobPublicService().find_active(db_session, project_id, "video")
    assert job is not None
    completed = service.process_job(db_session, job.id)

    # 断言 1：成片完成，且交付门给出结论
    assert completed.status == "completed", completed.error_code
    gate = completed.gate_report
    assert gate is not None
    assert gate["status"] in {"ok", "warn"}

    # 断言 2：本地合成器会烧录 AIGC 标识 → 标识检查必须是 ok
    checks = {item["id"]: item for item in gate["checks"]}
    assert checks["aigc_label"]["level"] == "ok", checks["aigc_label"]["message"]

    # 断言 3：真实视频才能抽帧 → 不应出现 contact_sheet 的 warn，且拼图 URL 非空
    assert "contact_sheet" not in checks
    assert gate["contact_sheet_url"]

    # 断言 4：成片规格 + 交付门确认才能解锁下载
    video = b"".join(object_storage.read_object(object_key=completed.final_object_key))
    assert inspect_video_dimensions(video) == (WIDTH, HEIGHT)

    before = client.get(f"/api/v1/projects/{project_id}/video/gate").json()["data"]
    pending = [
        item["id"] for item in before["checks"]
        if item["level"] == "warn" and item["id"] not in before["acknowledged"]
    ]
    if pending:
        assert before["download_allowed"] is False
        ack = client.post(f"/api/v1/projects/{project_id}/video/gate/ack", json={"check_ids": pending})
        assert ack.status_code == 200
        assert ack.json()["data"]["download_allowed"] is True
    else:
        assert before["download_allowed"] is True