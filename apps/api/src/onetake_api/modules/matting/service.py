from __future__ import annotations

from dataclasses import dataclass, replace

from sqlalchemy.orm import Session

from onetake_api.config import get_settings
from onetake_api.integrations.mock_matting.adapter import MockMattingAdapter
from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.integrations.photoroom_matting.adapter import PhotoroomMattingAdapter
from onetake_api.modules.job.domain import Job
from onetake_api.modules.job.public import JobPublicService
from onetake_api.modules.matting.domain import RUN_FAILED, RUN_QUEUED, RUN_RUNNING, RUN_SUCCEEDED, MattingRun
from onetake_api.modules.matting.repository import MattingRepository
from onetake_api.modules.outbox.public import OutboxPublicService
from onetake_api.platform.clock import SystemClock
from onetake_api.platform.errors import DomainError
from onetake_api.platform.ids import new_id


@dataclass(frozen=True)
class MattingStartResult:
    run: MattingRun
    job: Job


class MattingProviderError(DomainError):
    code = "MATTING_PROVIDER_ERROR"
    http_status = 502
    retryable = True


def _adapter():
    settings = get_settings()
    if settings.mock_providers:
        return MockMattingAdapter()
    return PhotoroomMattingAdapter(
        api_key=settings.photoroom_api_key,
        endpoint=settings.photoroom_endpoint,
    )


class MattingApplicationService:
    def __init__(self) -> None:
        self._repository = MattingRepository()
        self._jobs = JobPublicService()
        self._outbox = OutboxPublicService()
        self._clock = SystemClock()

    def start(
        self,
        session: Session,
        *,
        project_id: str,
        main_image_version_id: str,
        image_edit_run_id: str,
        source_object_key: str,
        pipeline_run_id: str,
        input_hash: str,
    ) -> MattingStartResult:
        provider = _adapter().provider_name
        now = self._clock.now()
        run_id = new_id("mat")
        output_object_key = f"projects/{project_id}/main-image/{main_image_version_id}/matted.png"
        run = MattingRun(
            id=run_id,
            project_id=project_id,
            main_image_version_id=main_image_version_id,
            image_edit_run_id=image_edit_run_id,
            status=RUN_QUEUED,
            provider=provider,
            source_object_key=source_object_key,
            output_object_key=output_object_key,
            size_bytes=None,
            error_code=None,
            created_at=now,
            updated_at=now,
            completed_at=None,
        )
        self._repository.add(session, run)
        session.flush()
        job = self._jobs.create(
            session,
            project_id=project_id,
            pipeline_run_id=pipeline_run_id,
            job_type="matting",
            provider=provider,
            input_hash=input_hash,
            idempotency_key=f"matting:{project_id}:{main_image_version_id}",
            reference_id=run.id,
        )
        return MattingStartResult(run=run, job=job)

    def get(self, session: Session, run_id: str) -> MattingRun | None:
        return self._repository.get(session, run_id)

    def latest_for_version(self, session: Session, version_id: str) -> MattingRun | None:
        return self._repository.latest_for_version(session, version_id)

    def process_job(
        self,
        session: Session,
        *,
        job_id: str,
        storage: ObjectStoragePublicService,
    ) -> MattingRun:
        job = self._jobs.get(session, job_id)
        if not job or job.job_type != "matting" or job.status not in {"queued", "running"}:
            raise MattingProviderError("去背任务不存在或不可执行")
        run = self._repository.get(session, job.reference_id)
        if not run:
            raise MattingProviderError("去背运行不存在")

        now = self._clock.now()
        job = self._jobs.mark_running(session, job)
        run = replace(run, status=RUN_RUNNING, updated_at=now)
        self._repository.update(session, run)
        session.flush()

        try:
            source = b"".join(storage.read_object(object_key=run.source_object_key))
            matted = _adapter().remove_background(image_bytes=source)
            storage.put_bytes(object_key=run.output_object_key, content=matted, mime_type="image/png")
            now = self._clock.now()
            run = replace(run, status=RUN_SUCCEEDED, size_bytes=len(matted), updated_at=now, completed_at=now, error_code=None)
            self._repository.update(session, run)
            self._jobs.mark_succeeded(session, job)
            self._outbox.enqueue(
                session,
                event_name="MattingCompleted",
                aggregate_type="matting",
                aggregate_id=run.id,
                occurred_at=now,
                payload={"project_id": run.project_id, "version_id": run.main_image_version_id, "run_id": run.id, "size_bytes": len(matted)},
            )
        except DomainError as exc:
            now = self._clock.now()
            run = replace(run, status=RUN_FAILED, error_code=exc.code, updated_at=now, completed_at=now)
            self._repository.update(session, run)
            self._jobs.mark_failed(session, job, exc.code)
            self._outbox.enqueue(
                session,
                event_name="MattingFailed",
                aggregate_type="matting",
                aggregate_id=run.id,
                occurred_at=now,
                payload={"project_id": run.project_id, "version_id": run.main_image_version_id, "run_id": run.id, "error_code": exc.code},
            )
        except Exception as exc:
            now = self._clock.now()
            run = replace(run, status=RUN_FAILED, error_code="MATTING_PROVIDER_ERROR", updated_at=now, completed_at=now)
            self._repository.update(session, run)
            self._jobs.mark_failed(session, job, "MATTING_PROVIDER_ERROR")
            self._outbox.enqueue(
                session,
                event_name="MattingFailed",
                aggregate_type="matting",
                aggregate_id=run.id,
                occurred_at=now,
                payload={"project_id": run.project_id, "version_id": run.main_image_version_id, "run_id": run.id, "error_code": "MATTING_PROVIDER_ERROR"},
            )
            _ = exc
        return run
