from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onetake_api.modules.job.public import JobPublicService
from onetake_api.platform.database import get_session
from onetake_api.platform.errors import DomainError
from onetake_api.platform.request_context import get_request_id

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


class JobNotFoundError(DomainError):
    code = "JOB_NOT_FOUND"
    http_status = 404


class JobData(BaseModel):
    job_id: str
    project_id: str
    pipeline_run_id: str
    job_type: str
    status: str
    provider: str
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class JobResponse(BaseModel):
    data: JobData
    request_id: str


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: str, session: Session = Depends(get_session)) -> JobResponse:
    job = JobPublicService().get(session, job_id)
    if not job:
        raise JobNotFoundError("任务不存在")
    return JobResponse(
        data=JobData(job_id=job.id, project_id=job.project_id, pipeline_run_id=job.pipeline_run_id,
                     job_type=job.job_type, status=job.status, provider=job.provider,
                     error_code=job.error_code, created_at=job.created_at,
                     started_at=job.started_at, finished_at=job.finished_at),
        request_id=get_request_id(),
    )
