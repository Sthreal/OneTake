from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.modules.job.public import JobPublicService
from onetake_api.modules.pipeline.public import PipelinePublicService
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.modules.script.domain import STATUS_CONFIRMED, ScriptVersion
from onetake_api.modules.script.repository import ScriptRepository
from onetake_api.modules.subtitle.service import SubtitleApplicationService
from onetake_api.modules.voice.domain import VOICE_READY, VoiceRun
from onetake_api.modules.voice.repository import VoiceRepository


class FakeQueue:
    def enqueue(self, *_args, **_kwargs):
        return None


def _seed_voice(session: Session) -> tuple[str, str]:
    project = ProjectPublicService().create_project(session, product_name="字幕项目", product_note=None)
    now = datetime.now(UTC)
    script = ScriptVersion(
        id="scr_subtitle_test",
        project_id=project.id,
        version_number=1,
        status=STATUS_CONFIRMED,
        provider="mock",
        model="qwen-vl-plus",
        source_object_key="projects/test/main.png",
        facts={"product_name": "字幕项目", "product_note": None, "pain_point": "测试痛点", "selling_points": ["测试卖点"], "usage_scenario": "测试场景", "offer": None},
        hook="测试钩子",
        pain_point="测试痛点",
        selling_points=["测试卖点"],
        usage_scenario="测试场景",
        offer=None,
        cta="测试 CTA",
        full_text="第一句话。第二句话！第三句话？",
        character_count=15,
        estimated_duration_seconds=6.0,
        error_code=None,
        created_at=now,
        updated_at=now,
        completed_at=now,
        confirmed_at=now,
    )
    ScriptRepository().add(session, script)
    voice = VoiceRun(
        id="voi_subtitle_test",
        project_id=project.id,
        script_version_id="scr_subtitle_test",
        status=VOICE_READY,
        enabled=True,
        subtitle_enabled=True,
        provider="mock",
        model="cosyvoice-v2",
        voice_id="female",
        language="zh",
        speed=1.0,
        text="第一句话。第二句话！第三句话？",
        audio_object_key="projects/test/voice.wav",
        audio_mime_type="audio/wav",
        duration_seconds=6.0,
        timestamps=[],
        error_code=None,
        created_at=now,
        updated_at=now,
        completed_at=now,
        confirmed_at=None,
    )
    VoiceRepository().add(session, voice)
    session.flush()
    return project.id, voice.id


def test_subtitle_flow_success(db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch) -> None:
    project_id, voice_id = _seed_voice(db_session)
    service = SubtitleApplicationService(storage=object_storage)
    started = service.start(
        db_session,
        project_id=project_id,
        script_version_id="scr_subtitle_test",
        voice_run_id=voice_id,
        enabled=True,
        pipeline_run_id="run_subtitle_test",
    )
    db_session.commit()
    assert started.job is not None
    ready = service.process_job(db_session, started.job.id)
    assert ready.status == "ready"
    assert len(ready.segments) == 3
    assert ready.srt_object_key is not None
    assert PipelinePublicService().get_or_create(db_session, project_id).status == "subtitle_ready"


def test_subtitle_edit_creates_new_voice_job(db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch) -> None:
    monkeypatch.setattr("onetake_api.modules.voice.service.get_queue", lambda _name: FakeQueue())
    project_id, voice_id = _seed_voice(db_session)
    service = SubtitleApplicationService(storage=object_storage)
    started = service.start(db_session, project_id=project_id, script_version_id="scr_subtitle_test", voice_run_id=voice_id, enabled=True, pipeline_run_id="run_subtitle_edit")
    db_session.commit()
    assert started.job is not None
    service.process_job(db_session, started.job.id)
    ready = service.latest(db_session, project_id)
    assert ready is not None

    edited = service.update_segments(
        db_session,
        project_id=project_id,
        segments=[{"index": 1, "text": "修改后的第一句话。"}, {"index": 2, "text": "修改后的第二句话。"}, {"index": 3, "text": "修改后的第三句话。"}],
    )
    assert edited.segments[0]["text"] == "修改后的第一句话。"
    active = JobPublicService().find_active(db_session, project_id, "voice")
    assert active is not None

