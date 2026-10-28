from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy.orm import Session

from onetake_api.config import Settings, get_settings

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


class FakeContentQa:
    def evaluate_candidate(self, *_args, **_kwargs):
        return type("Report", (), {"passed": True, "score": 100})()


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
    service = VideoPlanApplicationService(storage=object_storage, composition=FakeComposition(), content_qa=FakeContentQa())
    plan = service.create_plan(db_session, project_id=project_id, mode="product", template_id="clean").plan
    assert plan is not None and plan.status == "plan_ready"
    service.request_video(db_session, project_id)
    job = JobPublicService().find_active(db_session, project_id, "video")
    assert job is not None
    completed = service.process_job(db_session, job.id)
    assert completed.status == "completed"
    assert completed.final_object_key is not None
    # Phase 5：交付门结论随成片落库
    gate = completed.gate_report
    assert gate is not None
    gate_check_ids = {item["id"] for item in gate["checks"]}
    # mock 合成器不烧录 AIGC 标识 → 如实记 warn（而不是冒充通过）
    assert "aigc_label" in gate_check_ids
    # 抽帧拼图对非视频产物不可用 → 同样如实记 warn
    assert "contact_sheet" in gate_check_ids
    assert gate["status"] in {"warn", "fail"}
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



class _CapturingQueue:
    """记录 enqueue 的 kwargs —— 用来断言"作业超时来自配置"，而不是某个硬编码值。"""

    def __init__(self, sink: dict) -> None:
        self._sink = sink

    def enqueue(self, task, *args, **kwargs):
        self._sink["task"] = task
        self._sink["args"] = args
        self._sink.update(kwargs)


def test_video_job_timeout_comes_from_settings(db_session: Session, object_storage: ObjectStoragePublicService, monkeypatch) -> None:
    """video 作业超时**必须可配**：原先硬编码 600 秒，而 one_shot 的全部 r2v 调用都在这一个作业里 ——

    实测（2026-10-14 `steps-d.json`）**单次** 10s 片段就要 438 秒；18s 脚本会切 2 次调用（13s+5s）
    → 600 秒必然被 rq 掐掉：用户点了"出片"，10 分钟后任务失败，**钱已经花了**。
    """
    captured: dict = {}
    monkeypatch.setattr(
        "onetake_api.modules.video_plan.service.get_queue",
        lambda _name: _CapturingQueue(captured),
    )
    monkeypatch.setenv("VIDEO_JOB_TIMEOUT_SECONDS", "1234")
    get_settings.cache_clear()

    project_id = _seed_video_inputs(db_session, object_storage)
    service = VideoPlanApplicationService(storage=object_storage, composition=FakeComposition(), content_qa=FakeContentQa())
    assert service.create_plan(db_session, project_id=project_id, mode="product", template_id="clean").plan is not None
    service.request_video(db_session, project_id)

    assert captured["job_timeout"] == 1234                       # 来自配置，不是硬编码
    assert captured["task"].endswith("run_video_job")


def test_video_job_timeout_default_outlives_two_r2v_calls() -> None:
    """默认值必须**大于** one_shot 最坏情况：2 次 r2v 调用 × 单次轮询上限 + 拼接/合成余量。

    这是一条不变量断言（不是钉死具体数字）：如果将来把单次预算调大而忘了调作业超时，这里会先红。
    """
    settings = Settings(_env_file=None)
    assert settings.video_job_timeout_seconds >= 2 * settings.wan_r2v_poll_timeout_seconds + 300


def test_one_shot_adapter_uses_configured_poll_timeout(monkeypatch) -> None:
    """r2v 适配器的**单次**轮询上限也要来自配置（适配器默认 600 秒会低于实测生成时间 → 单次就超时、钱白花）。"""
    from onetake_api.modules.video_plan import service as service_module

    captured: dict = {}

    class _FakeAdapter:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

        def generate_film(self, **_kwargs):
            return b"video-bytes", "task-r2v"

    class _FakeUploader:
        def __init__(self, **_kwargs) -> None:
            pass

        def upload_image(self, _content, _name):
            return "oss://tmp/ref.png"

    monkeypatch.setattr("onetake_api.integrations.wan_r2v.adapter.WanR2VAdapter", _FakeAdapter)
    monkeypatch.setattr(service_module, "DashScopeTemporaryUploader", _FakeUploader)
    monkeypatch.setenv("MOCK_PROVIDERS", "false")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.setenv("WAN_R2V_POLL_TIMEOUT_SECONDS", "900")
    get_settings.cache_clear()

    plan = SimpleNamespace(
        project_id="prj_r2v", mode="product", template_id="clean", duration_seconds=18.0,
        width=1080, height=1920, fps=30, id="vid_r2v",
    )
    call = SimpleNamespace(order=1, duration_seconds=10.0, prompt="生成一段 10 秒的竖版带货短视频", scene_ids=["scene_1"])

    service_module.VideoPlanApplicationService()._generate_film_clip(plan, call, [b"png-bytes"])

    assert captured["poll_timeout_seconds"] == 900
    assert captured["max_seconds"] == get_settings().wan_r2v_max_seconds
