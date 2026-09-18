from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.modules.job.public import JobPublicService
from onetake_api.modules.main_image.domain import MainImageVersion
from onetake_api.modules.main_image.repository import MainImageRepository
from onetake_api.modules.output.repository import OutputRepository
from onetake_api.modules.pipeline.public import PipelinePublicService
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.modules.subtitle.domain import SUBTITLE_CONFIRMED, SubtitleVersion
from onetake_api.modules.subtitle.repository import SubtitleRepository
from onetake_api.modules.video_plan.service import VideoPlanApplicationService
from onetake_api.modules.voice.domain import VOICE_CONFIRMED, VoiceRun
from onetake_api.modules.voice.repository import VoiceRepository


class FakeQueue:
    def enqueue(self, *_args, **_kwargs):
        return None


class FakeComposition:
    provider_name = "mock-video"

    def compose(self, _request):
        return b"final-mp4-video"


def _seed_video_inputs(session: Session, storage: ObjectStoragePublicService) -> str:
    project = ProjectPublicService().create_project(session, product_name="视频项目", product_note=None)
    now = datetime.now(UTC)
    image_key = f"projects/{project.id}/main.png"
    voice_key = f"projects/{project.id}/voice.wav"
    subtitle_key = f"projects/{project.id}/subtitle.srt"
    storage.put_bytes(object_key=image_key, content=b"main-image", mime_type="image/png")
    storage.put_bytes(object_key=voice_key, content=b"voice", mime_type="audio/wav")
    storage.put_bytes(object_key=subtitle_key, content="1\n00:00:00,000 --> 00:00:02,000\n字幕\n".encode("utf-8"), mime_type="application/x-subrip")
    MainImageRepository().add(session, MainImageVersion("miv_video", project.id, "ast_video", "confirmed", "edt_video", "mat_video", image_key, None, 2000, 2000, 1000, 1000, 1000, 0.82, None, now, now, now, now))
    VoiceRepository().add(session, VoiceRun("voi_video", project.id, "scr_video", VOICE_CONFIRMED, True, True, "mock", "cosyvoice-v2", "female", "zh", 1.0, "测试文案。", voice_key, "audio/wav", 18.0, [], None, now, now, now, now))
    SubtitleRepository().add(session, SubtitleVersion("sub_video", project.id, "scr_video", "voi_video", SUBTITLE_CONFIRMED, True, "zh", [{"index": 1, "text": "测试文案。", "start": 0, "end": 18}], subtitle_key, None, now, now, now, now))
    PipelinePublicService().mark_audio_subtitle_confirmed(session, project.id)
    session.flush()
    return project.id


def test_video_flow_completes_with_mock_renderer(db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch) -> None:
    monkeypatch.setattr("onetake_api.modules.video_plan.service.get_queue", lambda _name: FakeQueue())
    monkeypatch.setattr("onetake_api.modules.video_plan.service.render_base_video", lambda **_kwargs: b"base-video")
    monkeypatch.setattr(
        "onetake_api.modules.video_plan.service.validate_final_video",
        lambda *_args, **_kwargs: type("Metadata", (), {"width": 1080, "height": 1920, "fps": 30.0, "video_codec": "h264", "audio_codec": "aac"})(),
    )
    project_id = _seed_video_inputs(db_session, object_storage)
    service = VideoPlanApplicationService(storage=object_storage, composition=FakeComposition())
    plan = service.create_plan(db_session, project_id=project_id, mode="product", template_id="clean").plan
    assert plan is not None and plan.status == "plan_ready"
    service.request_video(db_session, project_id)
    job = JobPublicService().find_active(db_session, project_id, "video")
    assert job is not None
    completed = service.process_job(db_session, job.id)
    assert completed.status == "completed"
    assert completed.final_object_key is not None
    first_output = OutputRepository().latest(db_session, project_id)
    assert first_output is not None
    assert PipelinePublicService().get_or_create(db_session, project_id).status == "completed"

    second_plan = service.create_plan(db_session, project_id=project_id, mode="product", template_id="dynamic").plan
    assert second_plan is not None and second_plan.template_id == "dynamic"
    service.request_video(db_session, project_id)
    second_job = JobPublicService().find_active(db_session, project_id, "video")
    assert second_job is not None
    second_completed = service.process_job(db_session, second_job.id)
    assert second_completed.status == "completed"
    second_output = OutputRepository().latest(db_session, project_id)
    assert second_output is not None
    assert second_output.id != first_output.id
    assert second_output.object_key != first_output.object_key
    assert b"".join(object_storage.read_object(object_key=first_output.object_key)) == b"final-mp4-video"
