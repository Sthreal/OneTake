"""审稿闸契约：未 apply/ack 时付费视频 409 且零 provider 调用；等长失败只能 ack。"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from onetake_api.config import Settings, get_settings
from onetake_api.integrations.mock_script.adapter import MockScriptAdapter
from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.integrations.qwen_vl_script.adapter import (
    REVIEW_DIMENSIONS,
    QwenVlScriptError,
    ScriptReview,
)
from onetake_api.modules.asset.adapters.sqlalchemy_repository import SqlAlchemyAssetRepository
from onetake_api.modules.asset.domain.model import ASSET_STATUS_READY, create_pending_asset
from onetake_api.modules.content_plan.public import ContentPlanPublicService
from onetake_api.modules.job.public import JobPublicService
from onetake_api.modules.job.repository import JobModel
from onetake_api.modules.main_image.domain import MainImageVersion
from onetake_api.modules.main_image.repository import MainImageRepository
from onetake_api.modules.pipeline.orchestrator import PipelineOrchestrator
from onetake_api.modules.pipeline.public import PipelinePublicService
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.modules.script.domain import ScriptDraft
from onetake_api.modules.script.service import ScriptApplicationService
from onetake_api.modules.video_plan.public import VideoPlanPublicService
from onetake_api.modules.video_plan.segment_public import VideoSegmentPublicService
from onetake_api.modules.video_plan.service import VideoPlanApplicationService


class FakeQueue:
    def enqueue(self, *_args, **_kwargs):
        return None


class CountingQueue:
    enqueues = 0

    def enqueue(self, *_args, **_kwargs):
        CountingQueue.enqueues += 1


class CountingGenerator:
    calls = 0

    def __init__(self, *_args, **_kwargs):
        CountingGenerator.calls += 1


class _StubComposition:
    provider_name = "shotstack"


def _png() -> bytes:
    output = BytesIO()
    Image.new("RGBA", (300, 300), (255, 255, 255, 0)).save(output, format="PNG")
    return output.getvalue()


def _product_png() -> bytes:
    image = Image.new("RGB", (900, 900), (255, 255, 255))
    product = Image.new("RGB", (360, 520), (235, 78, 54))
    image.paste(product, (270, 190))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _seed_ready_script(client, db_session: Session, storage: ObjectStoragePublicService, monkeypatch, name: str) -> str:
    monkeypatch.setattr("onetake_api.modules.script.service.get_queue", lambda _name: FakeQueue())
    project = ProjectPublicService().create_project(db_session, product_name=name, product_note=None)
    key = f"projects/{project.id}/main-image/test/main-2000.png"
    storage.put_bytes(object_key=key, content=_png(), mime_type="image/png")
    now = datetime.now(UTC)
    MainImageRepository().add(
        db_session,
        MainImageVersion(
            id=f"miv_{project.id}",
            project_id=project.id,
            source_asset_id=f"ast_{project.id}",
            status="confirmed",
            image_edit_run_id="edt_gate",
            matting_run_id="mat_gate",
            transparent_object_key=key,
            jpg_object_key=None,
            png_width=2000,
            png_height=2000,
            jpg_width=1000,
            jpg_height=1000,
            jpg_size_bytes=1000,
            product_ratio=0.82,
            error_code=None,
            created_at=now,
            updated_at=now,
            completed_at=now,
            confirmed_at=now,
        ),
    )
    PipelinePublicService().mark_main_image_confirmed(db_session, project.id)
    db_session.flush()
    response = client.post(
        f"/api/v1/projects/{project.id}/script/generate",
        json={
            "pain_point": "清洗麻烦",
            "selling_points": ["杯身可拆卸", "适合随身携带"],
            "usage_scenario": "通勤和办公室",
            "offer": None,
        },
    )
    assert response.status_code == 202, response.text
    job = JobPublicService().find_active(db_session, project.id, "script")
    assert job is not None
    ScriptApplicationService(storage=storage).process_job(db_session, job.id)
    ready = client.get(f"/api/v1/projects/{project.id}/script").json()["data"]["version"]
    assert ready["status"] == "ready"
    assert ready["review_gate"]["status"] == "pending"
    return project.id


def _patch_queues(monkeypatch) -> None:
    for module in (
        "onetake_api.modules.recognition.service",
        "onetake_api.modules.main_image.service",
        "onetake_api.modules.script.service",
        "onetake_api.modules.voice.service",
        "onetake_api.modules.subtitle.api",
        "onetake_api.modules.video_plan.service",
    ):
        monkeypatch.setattr(f"{module}.get_queue", lambda _name: FakeQueue())


def _build_paid_project(session: Session, storage, monkeypatch, name: str):
    _patch_queues(monkeypatch)
    monkeypatch.setenv("AUTO_RUN_ENABLED", "true")
    get_settings.cache_clear()
    project = ProjectPublicService().create_project(session, product_name=name, product_note="轻便好用的随身水杯")
    content = _product_png()
    now = datetime.now(UTC)
    asset = create_pending_asset(
        asset_id=f"ast_{project.id}",
        project_id=project.id,
        object_key=f"projects/{project.id}/assets/ast/original.png",
        original_filename="商品.png",
        mime_type="image/png",
        size_bytes=len(content),
        width=900,
        height=900,
        sha256=sha256(content).hexdigest(),
        now=now,
    )
    asset = asset.__class__(**{**asset.__dict__, "status": ASSET_STATUS_READY})
    SqlAlchemyAssetRepository().add(session, asset)
    storage.put_bytes(object_key=asset.object_key, content=content, mime_type="image/png")
    session.flush()
    PipelineOrchestrator().resume_from_stage(session, project.id, "recognition")
    ContentPlanPublicService().generate(session, project.id)
    ContentPlanPublicService().confirm(session, project.id)
    view = VideoPlanPublicService().create_plan(
        session, project_id=project.id, mode="product", template_id="clean", path="segmented"
    )
    return project, view.plan


def _job_count(session: Session, project_id: str) -> int:
    return len(session.scalars(select(JobModel).where(JobModel.project_id == project_id)).all())


def _same_length_review(*, script_input, draft: ScriptDraft) -> ScriptReview:
    chars = list(draft.hook)
    for index, char in enumerate(chars):
        if char not in "。！？!?，,；;、 ":
            chars[index] = "呀" if char != "呀" else "啊"
            break
    revised = ScriptDraft(
        hook="".join(chars),
        pain_point=draft.pain_point,
        selling_points=tuple(draft.selling_points),
        usage_scenario=draft.usage_scenario,
        cta=draft.cta,
    )
    return ScriptReview(
        dimensions={name: {"passed": True, "reason": "ok"} for name in REVIEW_DIMENSIONS},
        revised=revised,
        changed_fields=["hook"],
        provider="mock-qwen-vl-plus",
        model="qwen-vl-plus",
    )


def _bloated_review(*, script_input, draft: ScriptDraft) -> ScriptReview:
    revised = ScriptDraft(
        hook=draft.hook + "这段改写故意写得很长远远超过原稿百分之二十所以整次审稿失败",
        pain_point=draft.pain_point,
        selling_points=tuple(draft.selling_points),
        usage_scenario=draft.usage_scenario,
        cta=draft.cta,
    )
    return ScriptReview(
        dimensions={name: {"passed": False, "reason": "too long"} for name in REVIEW_DIMENSIONS},
        revised=revised,
        changed_fields=["hook"],
        provider="mock-qwen-vl-plus",
        model="qwen-vl-plus",
    )


def test_confirm_requires_ack_then_edit_clears_the_gate(client, db_session, object_storage, monkeypatch) -> None:
    project_id = _seed_ready_script(client, db_session, object_storage, monkeypatch, "审稿确认")
    blocked = client.post(f"/api/v1/projects/{project_id}/script/confirm")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "SCRIPT_REVIEW_REQUIRED"
    early_ack = client.post(f"/api/v1/projects/{project_id}/script/review/apply", json={"action": "ack"})
    assert early_ack.status_code == 409
    assert early_ack.json()["error"]["code"] == "SCRIPT_REVIEW_REQUIRED"

    monkeypatch.setattr(MockScriptAdapter, "review_script", _same_length_review)
    reviewed = client.post(f"/api/v1/projects/{project_id}/script/review")
    assert reviewed.status_code == 200, reviewed.text
    body = reviewed.json()["data"]
    assert body["gate_status"] == "reviewed"
    assert body["length_ok"] is True
    assert body["changed_fields"] == ["hook"]
    assert body["blocks_paid_video"] is True
    assert set(body["dimensions"]) == set(REVIEW_DIMENSIONS)
    still_blocked = client.post(f"/api/v1/projects/{project_id}/script/confirm")
    assert still_blocked.status_code == 409

    applied = client.post(f"/api/v1/projects/{project_id}/script/review/apply", json={"action": "apply"})
    assert applied.status_code == 200, applied.text
    applied_body = applied.json()["data"]
    assert applied_body["gate_status"] == "passed"
    assert applied_body["decision"] == "applied"
    assert applied_body["blocks_paid_video"] is False
    assert applied_body["version"]["hook"] != body["version"]["hook"]
    assert 45 <= applied_body["version"]["character_count"] <= 72

    confirmed = client.post(f"/api/v1/projects/{project_id}/script/confirm")
    assert confirmed.status_code == 200, confirmed.text

    edited = client.patch(
        f"/api/v1/projects/{project_id}/script",
        json={"cta": "想确认这些已经写明的特点，现在就来进一步看看。"},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["data"]["version"]["review_gate"]["status"] == "pending"
    after_edit = client.post(f"/api/v1/projects/{project_id}/script/confirm")
    assert after_edit.status_code == 409
    assert after_edit.json()["error"]["code"] == "SCRIPT_REVIEW_REQUIRED"


def test_length_violation_rejects_apply_and_requires_ack(client, db_session, object_storage, monkeypatch) -> None:
    project_id = _seed_ready_script(client, db_session, object_storage, monkeypatch, "等长失败")
    monkeypatch.setattr(MockScriptAdapter, "review_script", _bloated_review)
    reviewed = client.post(f"/api/v1/projects/{project_id}/script/review")
    assert reviewed.status_code == 200, reviewed.text
    body = reviewed.json()["data"]
    assert body["gate_status"] == "failed"
    assert body["length_ok"] is False
    assert body["error_code"] == "SCRIPT_REVIEW_LENGTH"
    assert "hook" in body["length_errors"]
    assert body["blocks_paid_video"] is True
    original_hook = body["version"]["hook"]

    rejected = client.post(f"/api/v1/projects/{project_id}/script/review/apply", json={"action": "apply"})
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["error"]["code"] == "SCRIPT_REVIEW_LENGTH"
    assert client.get(f"/api/v1/projects/{project_id}/script").json()["data"]["version"]["hook"] == original_hook

    acked = client.post(f"/api/v1/projects/{project_id}/script/review/apply", json={"action": "ack"})
    assert acked.status_code == 200, acked.text
    assert acked.json()["data"]["gate_status"] == "passed"
    assert acked.json()["data"]["decision"] == "acked"
    assert acked.json()["data"]["version"]["hook"] == original_hook
    confirmed = client.post(f"/api/v1/projects/{project_id}/script/confirm")
    assert confirmed.status_code == 200, confirmed.text


def test_provider_failure_does_not_pass_until_ack(client, db_session, object_storage, monkeypatch) -> None:
    project_id = _seed_ready_script(client, db_session, object_storage, monkeypatch, "审稿超时")
    monkeypatch.setattr(MockScriptAdapter, "review_script", QwenVlScriptError("审稿超时"))
    failed = client.post(f"/api/v1/projects/{project_id}/script/review")
    assert failed.status_code == 502, failed.text
    assert failed.json()["error"]["code"] == "SCRIPT_PROVIDER_ERROR"
    apply_rejected = client.post(f"/api/v1/projects/{project_id}/script/review/apply", json={"action": "apply"})
    assert apply_rejected.status_code == 409
    acked = client.post(f"/api/v1/projects/{project_id}/script/review/apply", json={"action": "ack"})
    assert acked.status_code == 200, acked.text
    assert acked.json()["data"]["decision"] == "acked"


def test_off_and_warn_do_not_block_confirm(client, db_session, object_storage, monkeypatch, caplog) -> None:
    project_id = _seed_ready_script(client, db_session, object_storage, monkeypatch, "闸门关闭")
    monkeypatch.setenv("SCRIPT_REVIEW_GATE", "off")
    get_settings.cache_clear()
    opened = client.post(f"/api/v1/projects/{project_id}/script/confirm")
    assert opened.status_code == 200, opened.text

    project_warn = _seed_ready_script(client, db_session, object_storage, monkeypatch, "闸门警告")
    monkeypatch.setenv("SCRIPT_REVIEW_GATE", "warn")
    get_settings.cache_clear()
    with caplog.at_level(logging.WARNING):
        warned = client.post(f"/api/v1/projects/{project_warn}/script/confirm")
    assert warned.status_code == 200, warned.text
    assert any("不拦截文案确认" in record.message for record in caplog.records)


def test_paid_video_blocked_until_ack_and_makes_no_provider_call(
    client, db_session, object_storage, monkeypatch, caplog
) -> None:
    project, plan = _build_paid_project(db_session, object_storage, monkeypatch, "审稿视频闸")
    segments = VideoSegmentPublicService().materialize_segments(db_session, project_id=project.id)
    assert segments
    segment_id = segments[0].id
    script = client.get(f"/api/v1/projects/{project.id}/script").json()["data"]["version"]
    assert script["status"] == "confirmed"
    assert script["review_gate"]["status"] == "pending"

    monkeypatch.setenv("SCRIPT_REVIEW_GATE", "enforce")
    get_settings.cache_clear()
    paid = Settings(
        mock_providers=False,
        composition_provider="shotstack",
        shotstack_render_price=1.0,
        wan_i2v_provider="mock",
        script_review_gate="enforce",
    )
    monkeypatch.setattr("onetake_api.modules.video_plan.service.get_settings", lambda: paid)
    monkeypatch.setattr("onetake_api.modules.video_plan.service.get_composition_provider", lambda: _StubComposition())
    CountingGenerator.calls = 0
    CountingQueue.enqueues = 0
    monkeypatch.setattr("onetake_api.modules.video_plan.segment_service.SegmentVideoGenerator", CountingGenerator)
    monkeypatch.setattr("onetake_api.modules.video_plan.keyframe_service.KeyframeGenerator", CountingGenerator)
    monkeypatch.setattr("onetake_api.modules.video_plan.service.get_queue", lambda _name: CountingQueue())

    pid = project.id
    jobs_before = _job_count(db_session, pid)
    paid_calls = [
        ("POST", f"/api/v1/projects/{pid}/video", None),
        ("POST", f"/api/v1/projects/{pid}/compose", None),
        ("POST", f"/api/v1/projects/{pid}/video/batch", None),
        ("POST", f"/api/v1/projects/{pid}/video/segments/{segment_id}/candidates", {}),
        ("POST", f"/api/v1/projects/{pid}/video/segments/{segment_id}/retake", {"symptom": "blurry"}),
        ("POST", f"/api/v1/projects/{pid}/video/keyframes/scene_1/candidates", {"mode": "integrated", "n": 1}),
    ]
    for method, url, body in paid_calls:
        response = client.request(method, url, json=body)
        assert response.status_code == 409, (url, response.status_code, response.text)
        assert response.json()["error"]["code"] == "SCRIPT_REVIEW_REQUIRED", (url, response.text)
    assert _job_count(db_session, pid) == jobs_before
    assert CountingGenerator.calls == 0
    assert CountingQueue.enqueues == 0
    assert PipelinePublicService().list_cost_approvals(db_session, pid) == []

    reviewed = client.post(f"/api/v1/projects/{pid}/script/review")
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["data"]["gate_status"] == "reviewed"
    still = client.post(f"/api/v1/projects/{pid}/video")
    assert still.status_code == 409
    assert still.json()["error"]["code"] == "SCRIPT_REVIEW_REQUIRED"
    assert CountingGenerator.calls == 0

    monkeypatch.setenv("SCRIPT_REVIEW_GATE", "warn")
    get_settings.cache_clear()
    with caplog.at_level(logging.WARNING):
        warned = client.post(f"/api/v1/projects/{pid}/video")
    assert warned.status_code == 409, warned.text
    assert warned.json()["error"]["code"] == "COST_APPROVAL_REQUIRED"
    assert any("不拦截付费视频" in record.message for record in caplog.records)
    assert CountingGenerator.calls == 0

    monkeypatch.setenv("SCRIPT_REVIEW_GATE", "off")
    get_settings.cache_clear()
    opened = client.post(f"/api/v1/projects/{pid}/video")
    assert opened.status_code == 409, opened.text
    assert opened.json()["error"]["code"] == "COST_APPROVAL_REQUIRED"

    monkeypatch.setenv("SCRIPT_REVIEW_GATE", "enforce")
    get_settings.cache_clear()
    acked = client.post(f"/api/v1/projects/{pid}/script/review/apply", json={"action": "ack"})
    assert acked.status_code == 200, acked.text
    assert acked.json()["data"]["gate_status"] == "passed"
    released = client.post(f"/api/v1/projects/{pid}/video")
    assert released.status_code == 409, released.text
    assert released.json()["error"]["code"] == "COST_APPROVAL_REQUIRED"
    assert CountingGenerator.calls == 0
    assert CountingQueue.enqueues == 0

    VideoPlanApplicationService().approve_cost(db_session, project_id=pid, plan_id=plan.id, approved_by="tester")
    db_session.commit()
    accepted = client.post(f"/api/v1/projects/{pid}/video")
    assert accepted.status_code == 202, accepted.text
    assert CountingGenerator.calls == 0
    assert CountingQueue.enqueues == 1


@pytest.fixture(autouse=True)
def _declare_no_queue_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("onetake_api.modules.pipeline.orchestrator._queue_has_worker", lambda: False)
