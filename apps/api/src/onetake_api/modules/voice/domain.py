from dataclasses import dataclass
from datetime import datetime

VOICE_QUEUED = "queued"
VOICE_GENERATING = "generating"
VOICE_READY = "ready"
VOICE_CONFIRMED = "confirmed"
VOICE_FAILED = "failed"


@dataclass(frozen=True)
class VoiceRun:
    id: str
    project_id: str
    script_version_id: str
    status: str
    enabled: bool
    subtitle_enabled: bool
    provider: str
    model: str
    voice_id: str
    language: str
    speed: float
    text: str
    audio_object_key: str | None
    audio_mime_type: str | None
    duration_seconds: float | None
    timestamps: list
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    confirmed_at: datetime | None
