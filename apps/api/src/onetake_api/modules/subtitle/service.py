from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace

from sqlalchemy.orm import Session

from onetake_api.integrations.object_storage.dependencies import get_object_storage
from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.modules.job.domain import Job
from onetake_api.modules.job.public import JobPublicService
from onetake_api.modules.outbox.public import OutboxPublicService
from onetake_api.modules.pipeline.public import PipelinePublicService
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.modules.subtitle.domain import SUBTITLE_CONFIRMED, SUBTITLE_FAILED, SUBTITLE_GENERATING, SUBTITLE_QUEUED, SUBTITLE_READY, SubtitleVersion
from onetake_api.modules.subtitle.repository import SubtitleRepository
from onetake_api.modules.voice.public import VoicePublicService
from onetake_api.platform.clock import SystemClock
from onetake_api.platform.errors import DomainError
from onetake_api.platform.ids import new_id
from onetake_api.platform.queue import get_queue

MAX_SEGMENTS = 12
MIN_SEGMENT_SECONDS = 0.8
MAX_SEGMENT_SECONDS = 5.0
_SENTENCE_RE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?")


class SubtitleNotFoundError(DomainError):
    code = "SUBTITLE_NOT_FOUND"
    http_status = 404


class SubtitleConflictError(DomainError):
    code = "SUBTITLE_CONFLICT"
    http_status = 409
    retryable = True


class SubtitleValidationError(DomainError):
    code = "SUBTITLE_VALIDATION_ERROR"
    http_status = 422


@dataclass(frozen=True)
class SubtitleStartResult:
    version: SubtitleVersion
    job: Job | None


def _split_text(text: str) -> list[str]:
    raw = [item.strip() for item in _SENTENCE_RE.findall(text) if item.strip()]
    if not raw:
        return [text.strip()] if text.strip() else []
    while len(raw) > MAX_SEGMENTS:
        merged = []
        cursor = 0
        while cursor < len(raw):
            if cursor + 1 < len(raw):
                merged.append(raw[cursor] + raw[cursor + 1])
                cursor += 2
            else:
                merged.append(raw[cursor])
                cursor += 1
        raw = merged
    return raw


def _build_segments(text: str, duration_seconds: float) -> list[dict]:
    sentences = _split_text(text)
    if not sentences:
        return []
    clean_lengths = [max(1, len(re.sub(r"\s+", "", item))) for item in sentences]
    total_weight = sum(clean_lengths)
    duration = max(float(duration_seconds), len(sentences) * MIN_SEGMENT_SECONDS)
    segments = []
    cursor = 0.0
    for index, (sentence, weight) in enumerate(zip(sentences, clean_lengths), start=1):
        segment_duration = duration * weight / total_weight
        segment_duration = min(MAX_SEGMENT_SECONDS, max(MIN_SEGMENT_SECONDS, segment_duration))
        start = cursor
        end = min(duration, start + segment_duration)
        segments.append({"index": index, "text": sentence, "start": round(start, 3), "end": round(end, 3)})
        cursor = end
    if segments:
        segments[-1]["end"] = round(duration, 3)
    return segments


def _format_srt(segments: list[dict]) -> str:
    def timestamp(seconds: float) -> str:
        total_ms = max(0, int(round(seconds * 1000)))
        hours, remainder = divmod(total_ms, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        secs, millis = divmod(remainder, 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    blocks = []
    for index, segment in enumerate(segments, start=1):
        blocks.append(f"{index}\n{timestamp(segment['start'])} --> {timestamp(segment['end'])}\n{segment['text']}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


class SubtitleApplicationService:
    def __init__(self, storage: ObjectStoragePublicService | None = None) -> None:
        self._repository = SubtitleRepository()
        self._projects = ProjectPublicService()
        self._voices = VoicePublicService()
        self._jobs = JobPublicService()
        self._pipeline = PipelinePublicService()
        self._outbox = OutboxPublicService()
        self._clock = SystemClock()
        self._storage = storage

    @property
    def storage(self) -> ObjectStoragePublicService:
        return self._storage or get_object_storage()

    def latest(self, session: Session, project_id: str) -> SubtitleVersion | None:
        self._projects.get_project(session, project_id=project_id)
        return self._repository.latest(session, project_id)

    def start(
        self,
        session: Session,
        *,
        project_id: str,
        script_version_id: str,
        voice_run_id: str,
        enabled: bool,
        pipeline_run_id: str,
    ) -> SubtitleStartResult:
        active = self._jobs.find_active(session, project_id, "subtitle") if enabled else None
        if active:
            existing = self._repository.get(session, active.reference_id)
            if existing:
                return SubtitleStartResult(existing, active)
        now = self._clock.now()
        version = SubtitleVersion(
            id=new_id("sub"),
            project_id=project_id,
            script_version_id=script_version_id,
            voice_run_id=voice_run_id,
            status=SUBTITLE_QUEUED if enabled else SUBTITLE_READY,
            enabled=enabled,
            language="zh",
            segments=[],
            srt_object_key=None,
            error_code=None,
            created_at=now,
            updated_at=now,
            completed_at=None if enabled else now,
            confirmed_at=None,
        )
        self._repository.add(session, version)
        session.flush()
        if not enabled:
            self._pipeline.mark_subtitle_ready(session, project_id)
            self._outbox.enqueue(session, event_name="SubtitleSkipped", aggregate_type="subtitle", aggregate_id=version.id, occurred_at=now, payload={"project_id": project_id, "subtitle_id": version.id})
            return SubtitleStartResult(version, None)
        self._pipeline.mark_subtitle_queued(session, project_id)
        job = self._jobs.create(
            session,
            project_id=project_id,
            pipeline_run_id=pipeline_run_id,
            job_type="subtitle",
            provider="timeline-builder",
            input_hash=hashlib.sha256(f"{voice_run_id}:{script_version_id}".encode()).hexdigest(),
            idempotency_key=f"subtitle:{project_id}:{version.id}",
            reference_id=version.id,
        )
        return SubtitleStartResult(version, job)

    def update_segments(self, session: Session, *, project_id: str, segments: list[dict]) -> SubtitleVersion:
        self._projects.get_project(session, project_id=project_id)
        version = self._repository.latest(session, project_id)
        if version is None:
            raise SubtitleNotFoundError("字幕版本不存在")
        if not version.enabled or version.status not in {SUBTITLE_READY, SUBTITLE_CONFIRMED}:
            raise SubtitleConflictError("当前字幕状态不允许编辑")
        incoming = {int(item.get("index", 0)): str(item.get("text", "")).strip() for item in segments}
        updated_segments = []
        for item in version.segments:
            text = incoming.get(int(item["index"]), "")
            if not text:
                raise SubtitleValidationError("字幕文本不能为空")
            updated_segments.append({**item, "text": text})
        if not updated_segments:
            raise SubtitleValidationError("字幕不能为空")
        srt = _format_srt(updated_segments)
        key = f"projects/{project_id}/subtitle/{version.id}/subtitle.srt"
        self.storage.put_bytes(object_key=key, content=srt.encode("utf-8"), mime_type="application/x-subrip")
        now = self._clock.now()
        edited = replace(version, status=SUBTITLE_READY, segments=updated_segments, srt_object_key=key, error_code=None, updated_at=now, completed_at=now, confirmed_at=None)
        self._repository.update(session, edited)
        voice = self._voices.latest(session, project_id).run
        if voice is None:
            raise SubtitleConflictError("配音版本不存在")
        edited_text = "".join(item["text"] for item in updated_segments)
        self._voices.request(
            session,
            project_id=project_id,
            enabled=voice.enabled,
            subtitle_enabled=True,
            voice_id=voice.voice_id,
            language=voice.language,
            speed=voice.speed,
            text_override=edited_text,
        )
        return edited

    def confirm(self, session: Session, project_id: str) -> SubtitleVersion:
        self._projects.get_project(session, project_id=project_id)
        version = self._repository.latest(session, project_id)
        if version is None:
            raise SubtitleNotFoundError("字幕版本不存在")
        if version.status not in {SUBTITLE_READY, SUBTITLE_CONFIRMED}:
            raise SubtitleConflictError("字幕尚未准备确认")
        now = self._clock.now()
        confirmed = replace(version, status=SUBTITLE_CONFIRMED, updated_at=now, confirmed_at=now)
        self._repository.update(session, confirmed)
        session.flush()
        return confirmed

    def process_job(self, session: Session, job_id: str) -> SubtitleVersion:
        job = self._jobs.get(session, job_id)
        if not job or job.job_type != "subtitle" or job.status not in {"queued", "running"}:
            raise SubtitleNotFoundError("字幕任务不存在或不可执行")
        version = self._repository.get(session, job.reference_id)
        if version is None:
            raise SubtitleNotFoundError("字幕版本不存在")
        voice = self._voices.get_run(session, version.voice_run_id)
        if voice is None or voice.duration_seconds is None:
            raise SubtitleConflictError("配音时长不可用")
        job = self._jobs.mark_running(session, job)
        version = replace(version, status=SUBTITLE_GENERATING, updated_at=self._clock.now())
        self._repository.update(session, version)
        self._pipeline.mark_subtitle_generating(session, version.project_id)
        session.commit()
        try:
            segments = _build_segments(voice.text, voice.duration_seconds)
            srt = _format_srt(segments)
            key = f"projects/{version.project_id}/subtitle/{version.id}/subtitle.srt"
            self.storage.put_bytes(object_key=key, content=srt.encode("utf-8"), mime_type="application/x-subrip")
            now = self._clock.now()
            version = replace(version, status=SUBTITLE_READY, segments=segments, srt_object_key=key, error_code=None, updated_at=now, completed_at=now)
            self._repository.update(session, version)
            self._jobs.mark_succeeded(session, job)
            self._pipeline.mark_subtitle_ready(session, version.project_id)
            self._outbox.enqueue(session, event_name="SubtitleCompleted", aggregate_type="subtitle", aggregate_id=version.id, occurred_at=now, payload={"project_id": version.project_id, "subtitle_id": version.id, "segment_count": len(segments)})
            session.commit()
            return version
        except DomainError as exc:
            self._jobs.mark_failed(session, job, exc.code)
            return self._mark_failed(session, version, exc.code)
        except Exception:
            self._jobs.mark_failed(session, job, "SUBTITLE_GENERATION_ERROR")
            return self._mark_failed(session, version, "SUBTITLE_GENERATION_ERROR")

    def _mark_failed(self, session: Session, version: SubtitleVersion, error_code: str) -> SubtitleVersion:
        now = self._clock.now()
        failed = replace(version, status=SUBTITLE_FAILED, error_code=error_code, updated_at=now, completed_at=now)
        self._repository.update(session, failed)
        self._pipeline.mark_subtitle_failed(session, version.project_id)
        self._outbox.enqueue(session, event_name="SubtitleFailed", aggregate_type="subtitle", aggregate_id=version.id, occurred_at=now, payload={"project_id": version.project_id, "subtitle_id": version.id, "error_code": error_code})
        session.commit()
        return failed
