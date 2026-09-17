from dataclasses import dataclass
from datetime import datetime

RUN_QUEUED = "queued"
RUN_RUNNING = "running"
RUN_SUCCEEDED = "succeeded"
RUN_FAILED = "failed"


@dataclass(frozen=True)
class MattingRun:
    id: str
    project_id: str
    main_image_version_id: str
    image_edit_run_id: str
    status: str
    provider: str
    source_object_key: str
    output_object_key: str
    size_bytes: int | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
