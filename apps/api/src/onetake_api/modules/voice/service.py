from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace

from sqlalchemy.orm import Session

from onetake_api.config import get_settings
from onetake_api.integrations.cosyvoice.adapter import CosyVoiceV2Adapter
from onetake_api.integrations.mock_voice.adapter import MockVoiceAdapter
from onetake_api.integrations.object_storage.dependencies import get_object_storage
from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.modules.job.public import JobPublicService
from onetake_api.modules.outbox.public import OutboxPublicService
from onetake_api.modules.pipeline.public import PipelinePublicService
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.modules.script.domain import STATUS_CONFIRMED as SCRIPT_CONFIRMED
from onetake_api.modules.script.public import ScriptPublicService
from onetake_api.modules.voice.domain import VOICE_FAILED, VOICE_GENERATING, VOICE_QUEUED, VOICE_READY, VoiceRun
from onetake_api.modules.voice.repository import VoiceRepository
from onetake_api.platform.clock import SystemClock
from onetake_api.platform.errors import DomainError
from onetake_api.platform.ids import new_id
from onetake_api.platform.queue import get_queue

VOICE_URL_SECONDS = 3600


class VoiceNotFoundError(DomainError):
    code = "VOICE_NOT_FOUND"
    http_status = 404


class VoiceConflictError(DomainError):
    code = "VOICE_CONFLICT"
    http_status = 409
    retryable = True


class VoiceValidationError(DomainError):
    code = "VOICE_VALIDATION_ERROR"
    http_status = 422


class VoiceProviderConfigurationError(DomainError):
    code = "VOICE_PROVIDER_NOT_CONFIGURED"
    http_status = 422


@dataclass(frozen=True)
class VoiceView:
    run: VoiceRun | None
    audio_url: str | None


def _adapter():
    settings = get_settings()
    if settings.mock_providers or settings.voice_provider == "mock":
        return MockVoiceAdapter()
    if not settings.dashscope_api_key:
        raise VoiceProviderConfigurationError("真实配音缺少 DASHSCOPE_API_KEY")
    return CosyVoiceV2Adapter(api_key=settings.dashscope_api_key, model=settings.voice_model)


class VoiceApplicationService:
    def __init__(self, storage: ObjectStoragePublicService | None = None) -> None:
        self._repository = VoiceRepository()
        self._projects = ProjectPublicService()
        self._scripts = ScriptPublicService()
        self._jobs = JobPublicService()
        self._pipeline = PipelinePublicService()
        self._outbox = OutboxPublicService()
        self._clock = SystemClock()
        self._storage = storage

    @property
    def storage(self) -> ObjectStoragePublicService:
        return self._storage or get_object_storage()

    def _view(self, run: VoiceRun | None) -> VoiceView:
        if run is None or not run.enabled or not run.audio_object_key:
            return VoiceView(run=run, audio_url=None)
        url = self.storage.create_get_url(object_key=run.audio_object_key, expires_seconds=VOICE_URL_SECONDS).url
        return VoiceView(run=run, audio_url=url)

    def latest(self, session: Session, project_id: str) -> VoiceView:
        self._projects.get_project(session, project_id=project_id)
        return self._view(self._repository.latest(session, project_id))

    def request(
        self,
        session: Session,
        *,
        project_id: str,
        enabled: bool,
        voice_id: str,
        language: str,
        speed: float,
    ) -> VoiceView:
        self._projects.get_project(session, project_id=project_id)
        script_view = self._scripts.latest(session, project_id)
        script_version = script_view.version
        if script_version is None or script_version.status != SCRIPT_CONFIRMED:
            raise VoiceConflictError("请先确认文案，再生成配音")
        if not 0.5 <= speed <= 2.0:
            raise VoiceValidationError("语速必须在 0.5–2.0 之间")
        if language not in {"zh", "en"}:
            raise VoiceValidationError("当前仅支持中文和英文配音")
        normalized_voice = voice_id.strip()
        if not normalized_voice:
            raise VoiceValidationError("音色不能为空")

        active = self._jobs.find_active(session, project_id, "voice")
        if active:
            run = self._repository.get(session, active.reference_id)
            if run:
                return self._view(run)

        adapter = _adapter()
        now = self._clock.now()
        run = VoiceRun(
            id=new_id("voi"),
            project_id=project_id,
            script_version_id=script_version.id,
            status=VOICE_QUEUED if enabled else VOICE_READY,
            enabled=enabled,
            provider=adapter.provider_name,
            model=adapter.model,
            voice_id=normalized_voice,
            language=language,
            speed=speed,
            text=script_version.full_text,
            audio_object_key=None,
            audio_mime_type=None,
            duration_seconds=None,
            timestamps=[],
            error_code=None,
            created_at=now,
            updated_at=now,
            completed_at=None if enabled else now,
        )
        self._repository.add(session, run)
        session.flush()
        if not enabled:
            self._pipeline.mark_voice_ready(session, project_id)
            self._outbox.enqueue(session, event_name="VoiceSkipped", aggregate_type="voice", aggregate_id=run.id, occurred_at=now, payload={"project_id": project_id, "run_id": run.id})
            session.commit()
            return self._view(run)

        pipeline = self._pipeline.mark_voice_queued(session, project_id)
        input_hash = hashlib.sha256(f"{script_version.id}:{normalized_voice}:{language}:{speed}".encode()).hexdigest()
        job = self._jobs.create(
            session,
            project_id=project_id,
            pipeline_run_id=pipeline.id,
            job_type="voice",
            provider=adapter.provider_name,
            input_hash=input_hash,
            idempotency_key=f"voice:{project_id}:{run.id}",
            reference_id=run.id,
        )
        self._outbox.enqueue(session, event_name="VoiceRequested", aggregate_type="voice", aggregate_id=run.id, occurred_at=now, payload={"project_id": project_id, "run_id": run.id})
        session.commit()
        try:
            get_queue("voice").enqueue("onetake_api.modules.voice.worker_tasks.run_voice_job", job.id, job_id=job.id, job_timeout=180)
        except Exception as exc:
            self._jobs.mark_failed(session, job, "QUEUE_UNAVAILABLE")
            self._mark_failed(session, run, "QUEUE_UNAVAILABLE")
            raise VoiceConflictError("配音任务提交失败") from exc
        return self._view(run)

    def process_job(self, session: Session, job_id: str) -> VoiceRun:
        job = self._jobs.get(session, job_id)
        if not job or job.job_type != "voice" or job.status not in {"queued", "running"}:
            raise VoiceNotFoundError("配音任务不存在或不可执行")
        run = self._repository.get(session, job.reference_id)
        if run is None:
            raise VoiceNotFoundError("配音运行不存在")
        job = self._jobs.mark_running(session, job)
        run = replace(run, status=VOICE_GENERATING, updated_at=self._clock.now())
        self._repository.update(session, run)
        self._pipeline.mark_voice_generating(session, run.project_id)
        session.commit()
        try:
            result = _adapter().synthesize(text=run.text, voice_id=run.voice_id, language=run.language, speed=run.speed)
            object_key = f"projects/{run.project_id}/voice/{run.id}/voice.wav"
            self.storage.put_bytes(object_key=object_key, content=result.audio_bytes, mime_type=result.mime_type)
            now = self._clock.now()
            run = replace(
                run,
                status=VOICE_READY,
                audio_object_key=object_key,
                audio_mime_type=result.mime_type,
                duration_seconds=result.duration_seconds,
                timestamps=result.timestamps,
                error_code=None,
                updated_at=now,
                completed_at=now,
            )
            self._repository.update(session, run)
            self._jobs.mark_succeeded(session, job)
            self._pipeline.mark_voice_ready(session, run.project_id)
            self._outbox.enqueue(session, event_name="VoiceCompleted", aggregate_type="voice", aggregate_id=run.id, occurred_at=now, payload={"project_id": run.project_id, "run_id": run.id, "duration_seconds": run.duration_seconds})
            session.commit()
            return run
        except DomainError as exc:
            self._jobs.mark_failed(session, job, exc.code)
            return self._mark_failed(session, run, exc.code)
        except Exception:
            self._jobs.mark_failed(session, job, "VOICE_PROVIDER_ERROR")
            return self._mark_failed(session, run, "VOICE_PROVIDER_ERROR")

    def _mark_failed(self, session: Session, run: VoiceRun, error_code: str) -> VoiceRun:
        now = self._clock.now()
        failed = replace(run, status=VOICE_FAILED, error_code=error_code, updated_at=now, completed_at=now)
        self._repository.update(session, failed)
        self._pipeline.mark_voice_failed(session, run.project_id)
        self._outbox.enqueue(session, event_name="VoiceFailed", aggregate_type="voice", aggregate_id=run.id, occurred_at=now, payload={"project_id": run.project_id, "run_id": run.id, "error_code": error_code})
        session.commit()
        return failed
