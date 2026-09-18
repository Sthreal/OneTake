from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from onetake_api.modules.voice.domain import VoiceRun
from onetake_api.modules.voice.public import VoicePublicService
from onetake_api.modules.voice.service import VoiceView
from onetake_api.platform.database import get_session
from onetake_api.platform.request_context import get_request_id

router = APIRouter(prefix="/api/v1/projects/{project_id}/voice", tags=["voice"])


class VoiceRequest(BaseModel):
    enabled: bool = True
    voice_id: str = Field(min_length=1, max_length=80)
    language: str = Field(default="zh", pattern=r"^(zh|en)$")
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


class VoiceRunData(BaseModel):
    run_id: str
    project_id: str
    script_version_id: str
    status: str
    enabled: bool
    provider: str
    model: str
    voice_id: str
    language: str
    speed: float
    duration_seconds: float | None
    audio_url: str | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class VoiceData(BaseModel):
    run: VoiceRunData | None


class VoiceResponse(BaseModel):
    data: VoiceData
    request_id: str


def _run_data(run: VoiceRun, audio_url: str | None) -> VoiceRunData:
    return VoiceRunData(
        run_id=run.id,
        project_id=run.project_id,
        script_version_id=run.script_version_id,
        status=run.status,
        enabled=run.enabled,
        provider=run.provider,
        model=run.model,
        voice_id=run.voice_id,
        language=run.language,
        speed=run.speed,
        duration_seconds=run.duration_seconds,
        audio_url=audio_url,
        error_code=run.error_code,
        created_at=run.created_at,
        updated_at=run.updated_at,
        completed_at=run.completed_at,
    )


def _response(view: VoiceView) -> VoiceResponse:
    return VoiceResponse(
        data=VoiceData(run=_run_data(view.run, view.audio_url) if view.run else None),
        request_id=get_request_id(),
    )


@router.get("", response_model=VoiceResponse)
def get_voice(project_id: str, session: Session = Depends(get_session)) -> VoiceResponse:
    return _response(VoicePublicService().latest(session, project_id))


@router.post("", response_model=VoiceResponse, status_code=status.HTTP_202_ACCEPTED)
def request_voice(project_id: str, payload: VoiceRequest, session: Session = Depends(get_session)) -> VoiceResponse:
    view = VoicePublicService().request(
        session,
        project_id=project_id,
        enabled=payload.enabled,
        voice_id=payload.voice_id,
        language=payload.language,
        speed=payload.speed,
    )
    return _response(view)
