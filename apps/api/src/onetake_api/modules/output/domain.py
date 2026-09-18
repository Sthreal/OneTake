from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class OutputArtifact:
    id: str
    project_id: str
    kind: str
    object_key: str
    mime_type: str
    size_bytes: int
    duration_seconds: float
    created_at: datetime
    expires_at: datetime
    video_width: int | None = None
    video_height: int | None = None
    fps: float | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
