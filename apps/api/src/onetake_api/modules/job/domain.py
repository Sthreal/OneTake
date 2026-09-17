from dataclasses import dataclass
from datetime import datetime

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"


@dataclass(frozen=True)
class Job:
    id: str
    project_id: str
    pipeline_run_id: str
    reference_id: str
    job_type: str
    status: str
    idempotency_key: str
    provider: str
    input_hash: str
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
