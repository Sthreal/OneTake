from dataclasses import dataclass
from datetime import datetime

STATUS_QUEUED = "queued"
STATUS_EDITING = "editing"
STATUS_MATTING = "matting"
STATUS_PROCESSING = "processing"
STATUS_READY = "ready"
STATUS_CONFIRMED = "confirmed"
STATUS_FAILED = "failed"

ACTIVE_STATUSES = {STATUS_QUEUED, STATUS_EDITING, STATUS_MATTING, STATUS_PROCESSING}


@dataclass(frozen=True)
class MainImageVersion:
    id: str
    project_id: str
    source_asset_id: str
    status: str
    image_edit_run_id: str | None
    matting_run_id: str | None
    transparent_object_key: str | None
    jpg_object_key: str | None
    png_width: int | None
    png_height: int | None
    jpg_width: int | None
    jpg_height: int | None
    jpg_size_bytes: int | None
    product_ratio: float | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    confirmed_at: datetime | None
