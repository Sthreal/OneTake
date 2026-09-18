from dataclasses import dataclass
from datetime import datetime

PLAN_READY = "plan_ready"
VIDEO_GENERATING = "video_generating"
VIDEO_READY = "video_ready"
RENDERING = "rendering"
COMPLETED = "completed"
FAILED = "failed"


@dataclass(frozen=True)
class VideoPlan:
    id: str
    project_id: str
    mode: str
    template_id: str | None
    status: str
    duration_seconds: float
    width: int
    height: int
    fps: int
    voice_enabled: bool
    subtitle_enabled: bool
    main_image_object_key: str
    voice_object_key: str | None
    subtitle_object_key: str | None
    base_video_object_key: str | None
    final_object_key: str | None
    provider: str
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    confirmed_at: datetime | None
