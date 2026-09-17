from dataclasses import dataclass
from datetime import datetime

STATUS_ASSETS_READY = "assets_ready"
STATUS_RECOGNIZING = "recognizing"
STATUS_RECOGNITION_READY = "recognition_ready"
STATUS_RECOGNITION_CONFIRMED = "recognition_confirmed"
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
