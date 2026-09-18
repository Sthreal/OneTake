from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onetake_api.integrations.object_storage.dependencies import get_object_storage
from onetake_api.modules.output.repository import OutputRepository
from onetake_api.platform.database import get_session
from onetake_api.platform.request_context import get_request_id

router = APIRouter(prefix="/api/v1/projects/{project_id}/output", tags=["output"])


class OutputData(BaseModel):
    artifact_id: str
    kind: str
    mime_type: str
    size_bytes: int
    duration_seconds: float
    download_url: str
    expires_at: datetime
    video_width: int | None
    video_height: int | None
    fps: float | None
    video_codec: str | None
    audio_codec: str | None


class OutputResponse(BaseModel):
    data: OutputData | None
    request_id: str


@router.get("", response_model=OutputResponse)
def get_output(project_id: str, session: Session = Depends(get_session)) -> OutputResponse:
    artifact = OutputRepository().latest(session, project_id)
    data = None
    if artifact:
        url = get_object_storage().create_get_url(object_key=artifact.object_key, expires_seconds=24 * 60 * 60).url
        data = OutputData(artifact_id=artifact.id, kind=artifact.kind, mime_type=artifact.mime_type, size_bytes=artifact.size_bytes, duration_seconds=artifact.duration_seconds, download_url=url, expires_at=artifact.expires_at, video_width=artifact.video_width, video_height=artifact.video_height, fps=artifact.fps, video_codec=artifact.video_codec, audio_codec=artifact.audio_codec)
    return OutputResponse(data=data, request_id=get_request_id())
