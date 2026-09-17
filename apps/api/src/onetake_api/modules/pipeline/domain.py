from dataclasses import dataclass
from datetime import datetime

STATUS_ASSETS_READY = "assets_ready"
STATUS_RECOGNIZING = "recognizing"
STATUS_RECOGNITION_READY = "recognition_ready"
STATUS_RECOGNITION_CONFIRMED = "recognition_confirmed"
STATUS_MAIN_IMAGE_QUEUED = "main_image_queued"
STATUS_IMAGE_EDITING = "image_editing"
STATUS_MATTING = "matting"
STATUS_MAIN_IMAGE_READY = "main_image_ready"
STATUS_MAIN_IMAGE_CONFIRMED = "main_image_confirmed"
STATUS_SCRIPT_QUEUED = "script_queued"
STATUS_SCRIPT_GENERATING = "script_generating"
STATUS_SCRIPT_READY = "script_ready"
STATUS_SCRIPT_CONFIRMED = "script_confirmed"
STATUS_FAILED = "failed"


@dataclass(frozen=True)
class PipelineRun:
    id: str
    project_id: str
    status: str
    current_step: int
    state_version: int
    created_at: datetime
    updated_at: datetime
