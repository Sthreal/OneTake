from __future__ import annotations

from dataclasses import dataclass, replace

from sqlalchemy.orm import Session

from onetake_api.config import get_settings
from onetake_api.integrations.mock_image_edit.adapter import MockImageEditAdapter
from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.integrations.qwen_image_edit.adapter import QwenImageEditAdapter
from onetake_api.modules.image_edit.domain import (
    RUN_FAILED,
    RUN_QUEUED,
    RUN_RUNNING,
    RUN_SUCCEEDED,
    ImageEditRun,
)
from onetake_api.modules.image_edit.repository import ImageEditRepository
from onetake_api.modules.job.domain import Job
from onetake_api.modules.job.public import JobPublicService
from onetake_api.modules.outbox.public import OutboxPublicService
from onetake_api.platform.clock import SystemClock
from onetake_api.platform.errors import DomainError
from onetake_api.platform.ids import new_id


@dataclass(frozen=True)
class ImageEditStartResult:
    run: ImageEditRun
    job: Job


class ImageEditProviderError(DomainError):
    code = "IMAGE_EDIT_PROVIDER_ERROR"
    http_status = 502
    retryable = True


def _adapter():
    settings = get_settings()
    if settings.mock_providers or settings.image_edit_provider == "mock":
        return MockImageEditAdapter()
    return QwenImageEditAdapter(
        api_key=settings.dashscope_api_key,
        endpoint=settings.image_edit_endpoint,
        model=settings.image_edit_model,
    )


class ImageEditApplicationService:
    def __init__(self) -> None:
        self._repository = ImageEditRepository()
        self._jobs = JobPublicService()
        self._outbox = OutboxPublicService()
        self._clock = SystemClock()

    def start(
        self,
        session: Session,
        *,
        project_id: str,
        main_image_version_id: str,
        source_asset_id: str,
        source_object_key: str,
        source_mime_type: str,
        pipeline_run_id: str,
        input_hash: str,
    ) -> ImageEditStartResult:
        provider = _adapter().provider_name
        now = self._clock.now()
        run_id = new_id("edt")
        output_object_key = f"projects/{project_id}/main-image/{main_image_version_id}/edited.png"
        run = ImageEditRun(
            id=run_id,
            project_id=project_id,
            main_image_version_id=main_image_version_id,
            source_asset_id=source_asset_id,
            status=RUN_QUEUED,
            provider=provider,
            source_object_key=source_object_key,
            output_object_key=output_object_key,
            source_mime_type=source_mime_type,
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
            job_type="image_edit",
            provider=provider,
            input_hash=input_hash,
            idempotency_key=f"image-edit:{project_id}:{main_image_version_id}",
            reference_id=run.id,
        )
        return ImageEditStartResult(run=run, job=job)

    def get(self, session: Session, run_id: str) -> ImageEditRun | None:
        return self._repository.get(session, run_id)

    def latest_for_version(self, session: Session, version_id: str) -> ImageEditRun | None:
        return self._repository.latest_for_version(session, version_id)

    def process_job(
        self,
        session: Session,
        *,
        job_id: str,
        storage: ObjectStoragePublicService,
    ) -> ImageEditRun:
        job = self._jobs.get(session, job_id)
        if not job or job.job_type != "image_edit" or job.status not in {"queued", "running"}:
            raise ImageEditProviderError("图像编辑任务不存在或不可执行")
        run = self._repository.get(session, job.reference_id)
        if not run:
            raise ImageEditProviderError("图像编辑运行不存在")

        now = self._clock.now()
        job = self._jobs.mark_running(session, job)
        run = replace(run, status=RUN_RUNNING, updated_at=now)
        self._repository.update(session, run)
        session.flush()

        try:
            source = b"".join(storage.read_object(object_key=run.source_object_key))
            edited = _adapter().edit(image_bytes=source, mime_type=run.source_mime_type)
            storage.put_bytes(object_key=run.output_object_key, content=edited, mime_type="image/png")
            now = self._clock.now()
            run = replace(run, status=RUN_SUCCEEDED, size_bytes=len(edited), updated_at=now, completed_at=now, error_code=None)
            self._repository.update(session, run)
            self._jobs.mark_succeeded(session, job)
            self._outbox.enqueue(
                session,
                event_name="ImageEditCompleted",
                aggregate_type="image_edit",
                aggregate_id=run.id,
                occurred_at=now,
                payload={"project_id": run.project_id, "version_id": run.main_image_version_id, "run_id": run.id, "size_bytes": len(edited)},
            )
        except DomainError as exc:
            now = self._clock.now()
            run = replace(run, status=RUN_FAILED, error_code=exc.code, updated_at=now, completed_at=now)
            self._repository.update(session, run)
            self._jobs.mark_failed(session, job, exc.code)
            self._outbox.enqueue(
                session,
                event_name="ImageEditFailed",
                aggregate_type="image_edit",
                aggregate_id=run.id,
                occurred_at=now,
                payload={"project_id": run.project_id, "version_id": run.main_image_version_id, "run_id": run.id, "error_code": exc.code},
            )
        except Exception as exc:
            now = self._clock.now()
            run = replace(run, status=RUN_FAILED, error_code="IMAGE_EDIT_PROVIDER_ERROR", updated_at=now, completed_at=now)
            self._repository.update(session, run)
            self._jobs.mark_failed(session, job, "IMAGE_EDIT_PROVIDER_ERROR")
            self._outbox.enqueue(
                session,
                event_name="ImageEditFailed",
                aggregate_type="image_edit",
                aggregate_id=run.id,
                occurred_at=now,
                payload={"project_id": run.project_id, "version_id": run.main_image_version_id, "run_id": run.id, "error_code": "IMAGE_EDIT_PROVIDER_ERROR"},
            )
            _ = exc
        return run
