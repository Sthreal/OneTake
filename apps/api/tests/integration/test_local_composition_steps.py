"""G2 辅助：逐步骤健康检查（当端到端失败时，用来快速定位是哪一步坏了）。

与 `test_local_composition_flow.py` 的区别：那个测"整体是否交付"，这个测"每一环是否健康"，
失败信息更直接（基片 → 商品图层 → 合成 → 规格 → 质检 → 抽帧拼图 → 交付门）。
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from onetake_api.integrations.media.local_composer import LocalCompositionAdapter
from onetake_api.integrations.media.video_utils import inspect_video_dimensions
from onetake_api.integrations.mock_video.renderer import validate_final_video
from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.modules.composition.port import CompositionRequest
from onetake_api.modules.video_plan.gate import build_gate_report
from onetake_api.modules.video_plan.service import VideoPlanApplicationService

from test_local_composition_flow import _FakeQueue, _accept_all_keyframes, _seed_project


def test_local_composition_steps_are_healthy(
    client: TestClient, db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch
) -> None:
    monkeypatch.setattr("onetake_api.modules.video_plan.service.get_queue", lambda _name: _FakeQueue())
    project_id = _seed_project(db_session, object_storage, name="步骤健康检查")
    _accept_all_keyframes(db_session, object_storage, project_id)
    service = VideoPlanApplicationService(storage=object_storage, composition=LocalCompositionAdapter())
    plan = service.create_plan(db_session, project_id=project_id, mode="product", template_id="clean").plan
    assert plan is not None

    main_image = b"".join(object_storage.read_object(object_key=plan.main_image_object_key))
    audio = b"".join(object_storage.read_object(object_key=plan.voice_object_key))
    base = service._create_base_video(db_session, plan, main_image, audio)
    assert inspect_video_dimensions(base) == (plan.width, plan.height)

    srt = b"".join(object_storage.read_object(object_key=plan.subtitle_object_key))
    # M4-03 提交 4：商品图层（叠加兜底）已整体删除，合成请求不再携带它
    final = service._composition.compose(CompositionRequest(
        base_video_bytes=base, audio_bytes=audio, srt_bytes=srt,
        duration_seconds=plan.duration_seconds,
        width=plan.width, height=plan.height, fps=plan.fps,
    ))
    assert inspect_video_dimensions(final) == (plan.width, plan.height)

    metadata = validate_final_video(
        final, expected_width=plan.width, expected_height=plan.height,
        expected_fps=plan.fps, expected_audio=True,
    )
    report = service._content_qa.evaluate_candidate(
        db_session, project_id=project_id, video_plan_id=plan.id, video_bytes=final, metadata=metadata,
        expected_audio=True, subtitle_embedded=True, product_layered=True, product_image_bytes=main_image,
    )
    assert report.status == "passed", [item.message for item in report.checks if not item.passed]
    assert report.signals is not None, "质检报告必须带上客观信号"

    sheet = service._store_contact_sheet(db_session, plan, final)
    assert sheet, "抽帧拼图应可用（真实视频）"

    gate = build_gate_report(
        db_session, project_id=project_id, video_bytes=final, contact_sheet_url=sheet,
        width=plan.width, height=plan.height, composition_provider=plan.provider,
    )
    checks = {item.id: item for item in gate.checks}
    assert checks["aigc_label"].level == "ok"