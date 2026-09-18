from dataclasses import dataclass
from datetime import datetime

SUBTITLE_QUEUED = "queued"
SUBTITLE_GENERATING = "generating"
SUBTITLE_READY = "ready"
SUBTITLE_CONFIRMED = "confirmed"
SUBTITLE_FAILED = "failed"


@dataclass(frozen=True)
class SubtitleVersion:
    id: str
    project_id: str
    script_version_id: str
    voice_run_id: str
    status: str
    enabled: bool
    language: str
    segments: list
    srt_object_key: str | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    confirmed_at: datetime | None
