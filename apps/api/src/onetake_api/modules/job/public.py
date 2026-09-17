from __future__ import annotations

from dataclasses import replace

from sqlalchemy.orm import Session

from onetake_api.modules.job.domain import Job, STATUS_FAILED, STATUS_QUEUED, STATUS_RUNNING, STATUS_SUCCEEDED
from onetake_api.modules.job.repository import JobRepository
from onetake_api.platform.clock import SystemClock
from onetake_api.platform.ids import new_id


class JobPublicService:
    def __init__(self) -> None:
        self._repository = JobRepository()
        self._clock = SystemClock()

    def create(self, session: Session, *, project_id: str, pipeline_run_id: str, job_type: str, provider: str, input_hash: str, idempotency_key: str, reference_id: str) -> Job:
        active = self._repository.find_active(session, project_id, job_type)
        if active:
            return active
        now = self._clock.now()
        job = Job(new_id("job"), project_id, pipeline_run_id, reference_id, job_type, STATUS_QUEUED, idempotency_key, provider, input_hash, None, now, None, None)
        self._repository.add(session, job)
        session.flush()
        return job

    def get(self, session: Session, job_id: str) -> Job | None:
        return self._repository.get(session, job_id)

    def find_active(self, session: Session, project_id: str, job_type: str) -> Job | None:
        return self._repository.find_active(session, project_id, job_type)

    def mark_running(self, session: Session, job: Job) -> Job:
        updated = replace(job, status=STATUS_RUNNING, started_at=self._clock.now())
        self._repository.update(session, updated)
        session.flush()
        return updated

    def mark_succeeded(self, session: Session, job: Job) -> Job:
        updated = replace(job, status=STATUS_SUCCEEDED, finished_at=self._clock.now())
        self._repository.update(session, updated)
        session.flush()
        return updated

    def mark_failed(self, session: Session, job: Job, error_code: str) -> Job:
        updated = replace(job, status=STATUS_FAILED, error_code=error_code, finished_at=self._clock.now())
        self._repository.update(session, updated)
        session.flush()
        return updated
