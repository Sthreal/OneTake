from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.modules.job.public import JobPublicService
from onetake_api.modules.pipeline.public import PipelinePublicService
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.modules.script.domain import STATUS_CONFIRMED, ScriptVersion
from onetake_api.modules.script.repository import ScriptRepository
from onetake_api.modules.voice.service import VoiceApplicationService


class FakeQueue:
    def enqueue(self, *_args, **_kwargs):
        return None


def _seed_confirmed_script(session: Session) -> str:
    project = ProjectPublicService().create_project(session, product_name="配音项目", product_note=None)
    now = datetime.now(UTC)
    script = ScriptVersion(
        id="scr_voice_test",
        project_id=project.id,
        version_number=1,
        status=STATUS_CONFIRMED,
        provider="mock",
        model="qwen-vl-plus",
        source_object_key="projects/test/main.png",
        facts={"product_name": "配音项目", "product_note": None, "pain_point": "测试痛点", "selling_points": ["测试卖点"], "usage_scenario": "测试场景", "offer": None},
        hook="测试钩子",
        pain_point="测试痛点",
        selling_points=["测试卖点"],
        usage_scenario="测试场景",
        offer=None,
        cta="测试 CTA",
        full_text="测试钩子。测试痛点。测试卖点。测试场景。测试 CTA。",
        character_count=20,
        estimated_duration_seconds=5.7,
        error_code=None,
        created_at=now,
        updated_at=now,
        completed_at=now,
        confirmed_at=now,
    )
    ScriptRepository().add(session, script)
    session.flush()
    return project.id


def test_voice_flow_success(db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch) -> None:
    monkeypatch.setattr("onetake_api.modules.voice.service.get_queue", lambda _name: FakeQueue())
    project_id = _seed_confirmed_script(db_session)
    service = VoiceApplicationService(storage=object_storage)
    view = service.request(db_session, project_id=project_id, enabled=True, subtitle_enabled=False, voice_id="female", language="zh", speed=1.0)
    assert view.run is not None and view.run.status == "queued"
    job = JobPublicService().find_active(db_session, project_id, "voice")
    assert job is not None
    ready = service.process_job(db_session, job.id)
    assert ready.status == "ready"
    assert ready.audio_object_key is not None
    assert ready.duration_seconds is not None
    assert PipelinePublicService().get_or_create(db_session, project_id).status == "subtitle_ready"


def test_voice_can_be_disabled(db_session: Session, object_storage: ObjectStoragePublicService) -> None:
    project_id = _seed_confirmed_script(db_session)
    service = VoiceApplicationService(storage=object_storage)
    view = service.request(db_session, project_id=project_id, enabled=False, subtitle_enabled=False, voice_id="female", language="zh", speed=1.0)
    assert view.run is not None
    assert view.run.status == "ready"
    assert view.run.audio_object_key is None
    assert view.audio_url is None
