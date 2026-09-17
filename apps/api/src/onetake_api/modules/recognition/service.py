from __future__ import annotations

import hashlib
from dataclasses import replace

from sqlalchemy.orm import Session

from onetake_api.integrations.mock_recognition.adapter import MockRecognitionAdapter, MockRecognitionError
from onetake_api.modules.asset.public import AssetPublicService
from onetake_api.modules.job.public import JobPublicService
from onetake_api.modules.outbox.public import OutboxPublicService
from onetake_api.modules.pipeline.public import PipelinePublicService
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.modules.recognition.domain import (
    RUN_CONFIRMED, RUN_FAILED, RUN_QUEUED, RUN_READY, RUN_RUNNING, RecognitionCandidate, RecognitionRun,
)
from onetake_api.modules.recognition.repository import RecognitionRepository
from onetake_api.platform.clock import SystemClock
from onetake_api.platform.errors import DomainError
from onetake_api.platform.ids import new_id
from onetake_api.platform.queue import get_queue


class RecognitionNotFoundError(DomainError):
    code = "RECOGNITION_NOT_FOUND"
    http_status = 404


class RecognitionConflictError(DomainError):
    code = "RECOGNITION_CONFLICT"
    http_status = 409


class RecognitionValidationError(DomainError):
    code = "RECOGNITION_VALIDATION_ERROR"
    http_status = 422


class RecognitionService:
    def __init__(self) -> None:
        self._repository = RecognitionRepository()
        self._projects = ProjectPublicService()
        self._assets = AssetPublicService()
        self._jobs = JobPublicService()
        self._pipeline = PipelinePublicService()
        self._outbox = OutboxPublicService()
        self._clock = SystemClock()

    def request(self, session: Session, project_id: str) -> RecognitionRun:
        self._projects.get_project(session, project_id=project_id)
        assets = [asset for asset in self._assets.list_assets(session, project_id=project_id) if asset.status == "ready"]
        if not assets:
            raise RecognitionValidationError("至少需要一张已完成上传的素材")
        active = self._jobs.find_active(session, project_id, "recognition")
        if active:
            run = self._repository.get_run(session, active.reference_id)
            if run:
                return run
        input_hash = hashlib.sha256("|".join(f"{asset.id}:{asset.sha256 or ''}" for asset in assets).encode()).hexdigest()
        now = self._clock.now()
        pipeline = self._pipeline.mark_recognizing(session, project_id)
        run = RecognitionRun(new_id("rec"), project_id, RUN_QUEUED, input_hash, None, None, None, now, now, None)
        self._repository.add_run(session, run)
        job = self._jobs.create(session, project_id=project_id, pipeline_run_id=pipeline.id, reference_id=run.id, job_type="recognition", provider="mock", input_hash=input_hash, idempotency_key=f"recognition:{project_id}:{input_hash}")
        session.commit()
        try:
            get_queue("recognition").enqueue("onetake_api.modules.recognition.worker_tasks.run_recognition_job", job.id, job_id=job.id, job_timeout=120)
        except Exception as exc:
            job = self._jobs.mark_failed(session, job, "QUEUE_UNAVAILABLE")
            run = replace(run, status=RUN_FAILED, error_code="QUEUE_UNAVAILABLE", updated_at=self._clock.now(), completed_at=self._clock.now())
            self._repository.update_run(session, run)
            self._pipeline.mark_failed(session, project_id)
            session.commit()
            raise RecognitionConflictError("识别任务提交失败") from exc
        return run

    def latest(self, session: Session, project_id: str) -> tuple[RecognitionRun | None, list[RecognitionCandidate]]:
        self._projects.get_project(session, project_id=project_id)
        run = self._repository.latest_run(session, project_id)
        return (run, self._repository.list_candidates(session, run.id) if run else [])

    def confirm(self, session: Session, project_id: str, run_id: str, candidate_id: str) -> RecognitionRun:
        self._projects.get_project(session, project_id=project_id)
        run = self._repository.get_run(session, run_id)
        if not run or run.project_id != project_id:
            raise RecognitionNotFoundError("识别任务不存在")
        if run.status != RUN_READY:
            raise RecognitionConflictError("识别任务尚未准备确认")
        candidate = self._repository.get_candidate(session, candidate_id)
        if not candidate or candidate.run_id != run.id:
            raise RecognitionValidationError("候选商品无效")
        now = self._clock.now()
        updated = replace(run, status=RUN_CONFIRMED, selected_asset_id=candidate.asset_id, selected_candidate_id=candidate.id, updated_at=now, completed_at=now)
        self._repository.update_run(session, updated)
        self._pipeline.mark_recognition_confirmed(session, project_id)
        self._outbox.enqueue(session, event_name="RecognitionConfirmed", aggregate_type="recognition", aggregate_id=run.id, occurred_at=now, payload={"project_id": project_id, "run_id": run.id, "asset_id": candidate.asset_id, "candidate_id": candidate.id})
        session.commit()
        return updated

    def process_job(self, session: Session, job_id: str) -> RecognitionRun:
        job = self._jobs.get(session, job_id)
        if not job or job.status not in {"queued", "running"}:
            raise RecognitionNotFoundError("识别任务不存在")
        run = self._repository.get_run(session, job.reference_id)
        if not run:
            raise RecognitionNotFoundError("识别运行不存在")
        job = self._jobs.mark_running(session, job)
        run = replace(run, status=RUN_RUNNING, updated_at=self._clock.now())
        self._repository.update_run(session, run)
        session.commit()
        assets = [asset for asset in self._assets.list_assets(session, project_id=job.project_id) if asset.status == "ready"]
        try:
            drafts = MockRecognitionAdapter().recognize(assets)
            now = self._clock.now()
            candidates = [RecognitionCandidate(new_id("cand"), run.id, draft.asset_id, draft.label, draft.confidence, draft.reason, now) for draft in drafts]
            self._repository.add_candidates(session, candidates)
            run = replace(run, status=RUN_READY, updated_at=now, completed_at=now, error_code=None)
            self._repository.update_run(session, run)
            self._pipeline.mark_recognition_ready(session, job.project_id)
            self._outbox.enqueue(session, event_name="RecognitionCompleted", aggregate_type="recognition", aggregate_id=run.id, occurred_at=now, payload={"project_id": job.project_id, "run_id": run.id, "candidate_count": len(candidates)})
            job = self._jobs.mark_succeeded(session, job)
        except MockRecognitionError as exc:
            now = self._clock.now()
            run = replace(run, status=RUN_FAILED, error_code=exc.code, updated_at=now, completed_at=now)
            self._repository.update_run(session, run)
            self._pipeline.mark_failed(session, job.project_id)
            job = self._jobs.mark_failed(session, job, exc.code)
            self._outbox.enqueue(session, event_name="RecognitionFailed", aggregate_type="recognition", aggregate_id=run.id, occurred_at=now, payload={"project_id": job.project_id, "run_id": run.id, "error_code": exc.code})
        session.commit()
        return run
