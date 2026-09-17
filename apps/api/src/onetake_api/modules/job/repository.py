from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from onetake_api.modules.job.domain import Job
from onetake_api.platform.database import Base


class JobModel(Base):
    __tablename__ = "jobs"
    __table_args__ = {"schema": "job"}

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    pipeline_run_id: Mapped[str] = mapped_column(String(40), nullable=False)
    reference_id: Mapped[str] = mapped_column(String(40), nullable=False)
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def _to_domain(model: JobModel) -> Job:
    return Job(
        id=model.id, project_id=model.project_id, pipeline_run_id=model.pipeline_run_id, reference_id=model.reference_id,
        job_type=model.job_type, status=model.status, idempotency_key=model.idempotency_key,
        provider=model.provider, input_hash=model.input_hash, error_code=model.error_code,
        created_at=model.created_at, started_at=model.started_at, finished_at=model.finished_at,
    )


class JobRepository:
    def add(self, session: Session, job: Job) -> None:
        session.add(JobModel(**job.__dict__))

    def get(self, session: Session, job_id: str) -> Job | None:
        model = session.get(JobModel, job_id)
        return _to_domain(model) if model else None

    def find_active(self, session: Session, project_id: str, job_type: str) -> Job | None:
        model = session.scalar(
            select(JobModel).where(
                JobModel.project_id == project_id,
                JobModel.job_type == job_type,
                JobModel.status.in_(["queued", "running"]),
            )
        )
        return _to_domain(model) if model else None

    def update(self, session: Session, job: Job) -> None:
        model = session.get(JobModel, job.id)
        if model:
            model.status = job.status
            model.error_code = job.error_code
            model.started_at = job.started_at
            model.finished_at = job.finished_at
