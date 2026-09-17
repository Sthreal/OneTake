from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace

from sqlalchemy.orm import Session

from onetake_api.integrations.object_storage.dependencies import get_object_storage
from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.modules.asset.public import AssetPublicService
from onetake_api.modules.image_edit.public import ImageEditPublicService
from onetake_api.modules.job.public import JobPublicService
from onetake_api.modules.main_image.domain import (
    ACTIVE_STATUSES,
    STATUS_CONFIRMED,
    STATUS_EDITING,
    STATUS_FAILED,
    STATUS_MATTING,
    STATUS_PROCESSING,
    STATUS_QUEUED,
    STATUS_READY,
    MainImageVersion,
)
from onetake_api.modules.main_image.image_processing import MainImageProcessingError, standardize_main_image
from onetake_api.modules.main_image.repository import MainImageRepository
from onetake_api.modules.matting.public import MattingPublicService
from onetake_api.modules.outbox.public import OutboxPublicService
from onetake_api.modules.pipeline.public import PipelinePublicService
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.modules.recognition.public import RecognitionPublicService
from onetake_api.platform.clock import SystemClock
from onetake_api.platform.errors import DomainError
from onetake_api.platform.ids import new_id
from onetake_api.platform.queue import get_queue

PREVIEW_URL_SECONDS = 60 * 60


class MainImageNotFoundError(DomainError):
    code = "MAIN_IMAGE_NOT_FOUND"
    http_status = 404


class MainImageConflictError(DomainError):
    code = "MAIN_IMAGE_CONFLICT"
    http_status = 409
    retryable = True


class MainImageValidationError(DomainError):
    code = "MAIN_IMAGE_VALIDATION_ERROR"
    http_status = 422


@dataclass(frozen=True)
class MainImageView:
    version: MainImageVersion
    png_url: str | None
    jpg_url: str | None


class MainImageApplicationService:
    def __init__(self, storage: ObjectStoragePublicService | None = None) -> None:
        self._repository = MainImageRepository()
        self._projects = ProjectPublicService()
        self._assets = AssetPublicService()
        self._recognition = RecognitionPublicService()
        self._pipeline = PipelinePublicService()
        self._image_edit = ImageEditPublicService()
        self._matting = MattingPublicService()
        self._jobs = JobPublicService()
        self._outbox = OutboxPublicService()
        self._clock = SystemClock()
        self._storage = storage

    @property
    def storage(self) -> ObjectStoragePublicService:
        return self._storage or get_object_storage()

    def _view(self, version: MainImageVersion | None) -> MainImageView | None:
        if version is None:
            return None
        png_url = None
        jpg_url = None
        if version.transparent_object_key:
            png_url = self.storage.create_get_url(
                object_key=version.transparent_object_key,
                expires_seconds=PREVIEW_URL_SECONDS,
            ).url
        if version.jpg_object_key:
            jpg_url = self.storage.create_get_url(
                object_key=version.jpg_object_key,
                expires_seconds=PREVIEW_URL_SECONDS,
            ).url
        return MainImageView(version=version, png_url=png_url, jpg_url=jpg_url)

    def latest(self, session: Session, project_id: str) -> MainImageView | None:
        self._projects.get_project(session, project_id=project_id)
        return self._view(self._repository.latest(session, project_id))

    def request(self, session: Session, project_id: str) -> MainImageView:
        self._projects.get_project(session, project_id=project_id)
        recognition_run, _ = self._recognition.latest(session, project_id)
        if not recognition_run or recognition_run.status != "confirmed" or not recognition_run.selected_asset_id:
            raise MainImageConflictError("请先确认识别出的商品主体")
        asset = self._assets.get_asset(session, asset_id=recognition_run.selected_asset_id)
        if asset is None or asset.project_id != project_id or asset.status != "ready":
            raise MainImageValidationError("已确认的商品素材不可用")

        latest = self._repository.latest(session, project_id)
        if latest and latest.status in ACTIVE_STATUSES:
            return self._view(latest)  # type: ignore[return-value]

        now = self._clock.now()
        version = MainImageVersion(
            id=new_id("miv"),
            project_id=project_id,
            source_asset_id=asset.id,
            status=STATUS_QUEUED,
            image_edit_run_id=None,
            matting_run_id=None,
            transparent_object_key=None,
            jpg_object_key=None,
            png_width=None,
            png_height=None,
            jpg_width=None,
            jpg_height=None,
            jpg_size_bytes=None,
            product_ratio=None,
            error_code=None,
            created_at=now,
            updated_at=now,
            completed_at=None,
            confirmed_at=None,
        )
        self._repository.add(session, version)
        session.flush()
        pipeline = self._pipeline.mark_main_image_queued(session, project_id)
        input_hash = hashlib.sha256(
            f"{asset.sha256 or asset.id}:{version.id}:{pipeline.id}".encode()
        ).hexdigest()
        edit_start = self._image_edit.start(
            session,
            project_id=project_id,
            main_image_version_id=version.id,
            source_asset_id=asset.id,
            source_object_key=asset.object_key,
            source_mime_type=asset.mime_type,
            pipeline_run_id=pipeline.id,
            input_hash=input_hash,
        )
        version = replace(version, image_edit_run_id=edit_start.run.id, updated_at=self._clock.now())
        self._repository.update(session, version)
        self._outbox.enqueue(
            session,
            event_name="MainImageRequested",
            aggregate_type="main_image",
            aggregate_id=version.id,
            occurred_at=now,
            payload={"project_id": project_id, "version_id": version.id, "source_asset_id": asset.id},
        )
        session.commit()

        try:
            get_queue("image_edit").enqueue(
                "onetake_api.modules.main_image.worker_tasks.run_image_edit_job",
                edit_start.job.id,
                job_id=edit_start.job.id,
                job_timeout=180,
            )
        except Exception as exc:
            edit_job = self._jobs.get(session, edit_start.job.id)
            if edit_job:
                self._jobs.mark_failed(session, edit_job, "QUEUE_UNAVAILABLE")
            self._mark_failed(session, version, "QUEUE_UNAVAILABLE")
            raise MainImageConflictError("主图任务提交失败") from exc
        return self._view(version)  # type: ignore[return-value]

    def confirm(self, session: Session, project_id: str) -> MainImageView:
        self._projects.get_project(session, project_id=project_id)
        version = self._repository.latest(session, project_id)
        if version is None:
            raise MainImageNotFoundError("主图版本不存在")
        if version.status != STATUS_READY:
            raise MainImageConflictError("主图尚未准备确认")
        now = self._clock.now()
        version = replace(version, status=STATUS_CONFIRMED, updated_at=now, confirmed_at=now)
        self._repository.update(session, version)
        self._pipeline.mark_main_image_confirmed(session, project_id)
        self._outbox.enqueue(
            session,
            event_name="MainImageConfirmed",
            aggregate_type="main_image",
            aggregate_id=version.id,
            occurred_at=now,
            payload={"project_id": project_id, "version_id": version.id},
        )
        session.commit()
        return self._view(version)  # type: ignore[return-value]

    def process_image_edit_job(self, session: Session, job_id: str) -> MainImageVersion:
        job = self._jobs.get(session, job_id)
        if not job or job.job_type != "image_edit":
            raise MainImageNotFoundError("图像编辑任务不存在")
        edit_run = self._image_edit.get(session, job.reference_id)
        if edit_run is None:
            raise MainImageNotFoundError("图像编辑运行不存在")
        version = self._repository.get(session, edit_run.main_image_version_id)
        if version is None:
            raise MainImageNotFoundError("主图版本不存在")

        self._pipeline.mark_image_editing(session, version.project_id)
        version = replace(version, status=STATUS_EDITING, updated_at=self._clock.now())
        self._repository.update(session, version)
        session.commit()

        edit_run = self._image_edit.process_job(session, job_id=job_id, storage=self.storage)
        if edit_run.status != "succeeded":
            return self._mark_failed(session, version, edit_run.error_code or "IMAGE_EDIT_PROVIDER_ERROR")

        pipeline = self._pipeline.get_or_create(session, version.project_id)
        matting_start = self._matting.start(
            session,
            project_id=version.project_id,
            main_image_version_id=version.id,
            image_edit_run_id=edit_run.id,
            source_object_key=edit_run.output_object_key,
            pipeline_run_id=pipeline.id,
            input_hash=hashlib.sha256(f"{edit_run.id}:{edit_run.output_object_key}".encode()).hexdigest(),
        )
        version = replace(version, status=STATUS_MATTING, matting_run_id=matting_start.run.id, updated_at=self._clock.now())
        self._repository.update(session, version)
        self._pipeline.mark_matting(session, version.project_id)
        session.commit()
        self._enqueue_or_fail(
            session,
            version=version,
            queue_name="matting",
            task_path="onetake_api.modules.main_image.worker_tasks.run_matting_job",
            job_id=matting_start.job.id,
            timeout=180,
        )
        return version

    def process_matting_job(self, session: Session, job_id: str) -> MainImageVersion:
        job = self._jobs.get(session, job_id)
        if not job or job.job_type != "matting":
            raise MainImageNotFoundError("去背任务不存在")
        matting_run = self._matting.get(session, job.reference_id)
        if matting_run is None:
            raise MainImageNotFoundError("去背运行不存在")
        version = self._repository.get(session, matting_run.main_image_version_id)
        if version is None:
            raise MainImageNotFoundError("主图版本不存在")

        matting_run = self._matting.process_job(session, job_id=job_id, storage=self.storage)
        if matting_run.status != "succeeded":
            return self._mark_failed(session, version, matting_run.error_code or "MATTING_PROVIDER_ERROR")

        pipeline = self._pipeline.get_or_create(session, version.project_id)
        finalize_job = self._jobs.create(
            session,
            project_id=version.project_id,
            pipeline_run_id=pipeline.id,
            job_type="main_image",
            provider="pillow",
            input_hash=hashlib.sha256(f"{matting_run.id}:{matting_run.output_object_key}".encode()).hexdigest(),
            idempotency_key=f"main-image:{version.project_id}:{version.id}",
            reference_id=version.id,
        )
        version = replace(version, status=STATUS_PROCESSING, updated_at=self._clock.now())
        self._repository.update(session, version)
        session.commit()
        self._enqueue_or_fail(
            session,
            version=version,
            queue_name="main_image",
            task_path="onetake_api.modules.main_image.worker_tasks.run_main_image_job",
            job_id=finalize_job.id,
            timeout=120,
        )
        return version

    def process_finalize_job(self, session: Session, job_id: str) -> MainImageVersion:
        job = self._jobs.get(session, job_id)
        if not job or job.job_type != "main_image":
            raise MainImageNotFoundError("主图任务不存在")
        version = self._repository.get(session, job.reference_id)
        if version is None:
            raise MainImageNotFoundError("主图版本不存在")
        if version.status not in {STATUS_PROCESSING, STATUS_MATTING, STATUS_QUEUED}:
            raise MainImageConflictError("主图版本当前状态不允许生成")

        job = self._jobs.mark_running(session, job)
        version = replace(version, status=STATUS_PROCESSING, updated_at=self._clock.now())
        self._repository.update(session, version)
        session.flush()

        try:
            matting_run = self._matting.get(session, version.matting_run_id or "")
            if matting_run is None or matting_run.status != "succeeded":
                raise MainImageProcessingError("去背结果不可用")
            source = b"".join(self.storage.read_object(object_key=matting_run.output_object_key))
            standardized = standardize_main_image(source)
            png_key = f"projects/{version.project_id}/main-image/{version.id}/main-2000.png"
            jpg_key = f"projects/{version.project_id}/main-image/{version.id}/main-1000.jpg"
            self.storage.put_bytes(object_key=png_key, content=standardized.png_bytes, mime_type="image/png")
            self.storage.put_bytes(object_key=jpg_key, content=standardized.jpg_bytes, mime_type="image/jpeg")
            now = self._clock.now()
            version = replace(
                version,
                status=STATUS_READY,
                transparent_object_key=png_key,
                jpg_object_key=jpg_key,
                png_width=standardized.png_width,
                png_height=standardized.png_height,
                jpg_width=standardized.jpg_width,
                jpg_height=standardized.jpg_height,
                jpg_size_bytes=standardized.jpg_size_bytes,
                product_ratio=standardized.product_ratio,
                error_code=None,
                updated_at=now,
                completed_at=now,
            )
            self._repository.update(session, version)
            self._jobs.mark_succeeded(session, job)
            self._pipeline.mark_main_image_ready(session, version.project_id)
            self._outbox.enqueue(
                session,
                event_name="MainImageReady",
                aggregate_type="main_image",
                aggregate_id=version.id,
                occurred_at=now,
                payload={
                    "project_id": version.project_id,
                    "version_id": version.id,
                    "png_object_key": png_key,
                    "jpg_object_key": jpg_key,
                    "jpg_size_bytes": standardized.jpg_size_bytes,
                    "product_ratio": standardized.product_ratio,
                },
            )
            session.commit()
            return version
        except DomainError as exc:
            self._jobs.mark_failed(session, job, exc.code)
            return self._mark_failed(session, version, exc.code)
        except Exception:
            self._jobs.mark_failed(session, job, "MAIN_IMAGE_PROCESSING_ERROR")
            return self._mark_failed(session, version, "MAIN_IMAGE_PROCESSING_ERROR")

    def _enqueue_or_fail(
        self,
        session: Session,
        *,
        version: MainImageVersion,
        queue_name: str,
        task_path: str,
        job_id: str,
        timeout: int,
    ) -> None:
        try:
            get_queue(queue_name).enqueue(task_path, job_id, job_id=job_id, job_timeout=timeout)
        except Exception as exc:
            job = self._jobs.get(session, job_id)
            if job:
                self._jobs.mark_failed(session, job, "QUEUE_UNAVAILABLE")
            self._mark_failed(session, version, "QUEUE_UNAVAILABLE")
            raise MainImageConflictError("主图子任务提交失败") from exc

    def _mark_failed(self, session: Session, version: MainImageVersion, error_code: str) -> MainImageVersion:
        now = self._clock.now()
        failed = replace(
            version,
            status=STATUS_FAILED,
            error_code=error_code,
            updated_at=now,
            completed_at=now,
        )
        self._repository.update(session, failed)
        self._pipeline.mark_main_image_failed(session, version.project_id)
        self._outbox.enqueue(
            session,
            event_name="MainImageFailed",
            aggregate_type="main_image",
            aggregate_id=version.id,
            occurred_at=now,
            payload={"project_id": version.project_id, "version_id": version.id, "error_code": error_code},
        )
        session.commit()
        return failed

