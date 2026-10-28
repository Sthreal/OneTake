"""批次 6 集成测：导出端点（档位 / 视频 / 封面预览）+ 交付门拦截 + 原片不覆盖。"""
from __future__ import annotations

import io
import subprocess
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from imageio_ffmpeg import get_ffmpeg_exe
from PIL import Image
from sqlalchemy.orm import Session

from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.modules.main_image.domain import MainImageVersion
from onetake_api.modules.main_image.repository import MainImageRepository
from onetake_api.modules.pipeline.public import PipelinePublicService
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.modules.subtitle.domain import SUBTITLE_CONFIRMED, SubtitleVersion
from onetake_api.modules.subtitle.repository import SubtitleRepository
from onetake_api.modules.video_plan.domain import COMPLETED, VideoPlan
from onetake_api.modules.video_plan.repository import VideoPlanRepository
from onetake_api.modules.video_plan.service import VideoPlanApplicationService
from onetake_api.modules.voice.domain import VOICE_CONFIRMED, VoiceRun
from onetake_api.modules.voice.repository import VoiceRepository

WIDTH, HEIGHT = 360, 640


def _video_bytes(*, width: int = WIDTH, height: int = HEIGHT, seconds: float = 2.0) -> bytes:
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "final.mp4"
        subprocess.run(
            [get_ffmpeg_exe(), "-y", "-f", "lavfi", "-i", f"testsrc=size={width}x{height}:rate=24:duration={seconds}",
             "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
            check=True, capture_output=True,
        )
        return path.read_bytes()


def _seed(session: Session, storage: ObjectStoragePublicService, name: str, *, with_final: bool, gate: dict | None):
    project = ProjectPublicService().create_project(session, product_name=name, product_note=None)
    now = datetime.now(UTC)
    main_key = f"projects/{project.id}/main.png"
    buffer = io.BytesIO()
    Image.new("RGB", (WIDTH, HEIGHT), (200, 60, 60)).save(buffer, format="PNG")
    storage.put_bytes(object_key=main_key, content=buffer.getvalue(), mime_type="image/png")
    MainImageRepository().add(session, MainImageVersion("miv", project.id, "ast", "confirmed", "edt", "mat", main_key, None, 2000, 2000, 1000, 1000, 1000, 0.9, None, now, now, now, now))
    VoiceRepository().add(session, VoiceRun("voi", project.id, "scr", VOICE_CONFIRMED, True, True, "mock", "cosyvoice-v2", "female", "zh", 1.0, "测试。", f"projects/{project.id}/v.wav", "audio/wav", 2.0, [], None, now, now, now, now))
    SubtitleRepository().add(session, SubtitleVersion("sub", project.id, "scr", "voi", SUBTITLE_CONFIRMED, True, "zh", [{"index": 1, "text": "测试。", "start": 0, "end": 2}], f"projects/{project.id}/s.srt", None, now, now, now, now))
    PipelinePublicService().mark_audio_subtitle_confirmed(session, project.id)
    plan = VideoPlanApplicationService(storage=storage).create_plan(
        session, project_id=project.id, mode="product", template_id="clean"
    ).plan
    assert plan is not None
    if with_final:
        key = f"projects/{project.id}/video/{plan.id}/final.mp4"
        storage.put_bytes(object_key=key, content=_video_bytes(), mime_type="video/mp4")
        plan = replace(
            plan, status=COMPLETED, final_object_key=key,
            gate_report=gate or {"project_id": project.id, "status": "ok", "mode": "enforce", "checks": []},
        )
        VideoPlanRepository().update(session, plan)
    elif gate is not None:
        plan = replace(plan, gate_report=gate)
        VideoPlanRepository().update(session, plan)
    session.commit()
    return project.id, plan


def _export(client: TestClient, project_id: str, **payload) -> object:
    return client.post(f"/api/v1/projects/{project_id}/export", json=payload)


def test_export_profiles_endpoint_lists_both(client: TestClient, db_session: Session, object_storage) -> None:
    project_id, _ = _seed(db_session, object_storage, "导出档位", with_final=False, gate=None)
    response = client.get(f"/api/v1/projects/{project_id}/export/profiles")
    assert response.status_code == 200
    keys = [item["key"] for item in response.json()["data"]]
    assert keys == ["douyin", "xiaohongshu"]


def test_douyin_export_is_passthrough_and_source_untouched(
    client: TestClient, db_session: Session, object_storage: ObjectStoragePublicService
) -> None:
    project_id, plan = _seed(db_session, object_storage, "抖音导出", with_final=True, gate=None)
    before = b"".join(object_storage.read_object(object_key=plan.final_object_key))

    response = _export(client, project_id, profile="douyin", kind="video")
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    # 源片是 360x640（测试用小片），抖音档要求 1080x1920 → 走"等比缩放 + 黑边"兜底，绝不裁切
    assert (data["width"], data["height"]) == (1080, 1920)
    assert data["size_bytes"] > 0 and data["bitrate_kbps"] > 0 and data["has_audio"] is True
    assert data["source_size_bytes"] == len(before)

    after = b"".join(object_storage.read_object(object_key=plan.final_object_key))
    assert after == before                                            # 原片不覆盖
    exported = b"".join(object_storage.read_object(
        object_key=f"projects/{project_id}/exports/{plan.id}/douyin/video.mp4"
    ))
    assert len(exported) > 0
    report = b"".join(object_storage.read_object(
        object_key=f"projects/{project_id}/exports/{plan.id}/douyin/export-report.json"
    ))
    # 报告落盘，且带的是**实测**值（源片尺寸/码率、导出件大小、有无音轨）
    assert b'"source_width": 360' in report and b'"source_height": 640' in report
    assert b'"source_bitrate_kbps"' in report and b'"has_audio": true' in report


def test_xiaohongshu_export_and_cover_use_target_frame(
    client: TestClient, db_session: Session, object_storage: ObjectStoragePublicService
) -> None:
    project_id, plan = _seed(db_session, object_storage, "小红书导出", with_final=True, gate=None)

    video = _export(client, project_id, profile="xiaohongshu", kind="video")
    assert video.status_code == 201, video.text
    assert (video.json()["data"]["width"], video.json()["data"]["height"]) == (1080, 1440)
    assert video.json()["data"]["strategy"] == "blur_pad"

    cover = _export(client, project_id, profile="xiaohongshu", kind="cover", at_seconds=0.5)
    assert cover.status_code == 201, cover.text
    assert (cover.json()["data"]["width"], cover.json()["data"]["height"]) == (1080, 1440)
    assert cover.json()["data"]["at_seconds"] == 0.5
    stored = b"".join(object_storage.read_object(
        object_key=f"projects/{project_id}/exports/{plan.id}/xiaohongshu/cover-500ms.png"
    ))
    assert stored.startswith(b"\x89PNG") and Image.open(io.BytesIO(stored)).size == (1080, 1440)


def test_export_blocked_when_gate_has_unacknowledged_warn(
    client: TestClient, db_session: Session, object_storage
) -> None:
    gate = {
        "project_id": "ignored", "status": "warn", "mode": "enforce",
        "checks": [{"id": "contact_sheet", "level": "warn", "label": "抽帧复核", "message": "抽帧拼图不可用"}],
    }
    project_id, _ = _seed(db_session, object_storage, "交付门拦截", with_final=True, gate=gate)
    response = _export(client, project_id, profile="douyin")
    assert response.status_code == 409, response.text
    assert "EXPORT_BLOCKED_BY_GATE" in response.text
    assert "contact_sheet" in response.text


def test_export_not_ready_without_final_video(client: TestClient, db_session: Session, object_storage) -> None:
    project_id, _ = _seed(db_session, object_storage, "没有成片", with_final=False, gate=None)
    response = _export(client, project_id, profile="douyin")
    assert response.status_code == 409 and "EXPORT_NOT_READY" in response.text


def test_export_rejects_unknown_profile(client: TestClient, db_session: Session, object_storage) -> None:
    project_id, _ = _seed(db_session, object_storage, "未知档位", with_final=True, gate=None)
    response = _export(client, project_id, profile="bilibili")
    assert response.status_code == 400 and "EXPORT_PROFILE_INVALID" in response.text