from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onetake_api.modules.pipeline.public import PipelinePublicService
from onetake_api.modules.subtitle.api import SubtitleData, _data as subtitle_data
from onetake_api.modules.subtitle.public import SubtitlePublicService
from onetake_api.modules.voice.api import VoiceData, _run_data as voice_run_data
from onetake_api.modules.voice.public import VoicePublicService
from onetake_api.platform.database import get_session
from onetake_api.platform.request_context import get_request_id

router = APIRouter(prefix="/api/v1/projects/{project_id}/audio-subtitle", tags=["audio-subtitle"])


class AudioSubtitleData(BaseModel):
    voice: VoiceData
    subtitle: SubtitleData


class AudioSubtitleResponse(BaseModel):
    data: AudioSubtitleData
    request_id: str


def _response(session: Session, project_id: str) -> AudioSubtitleResponse:
    voice = VoicePublicService().latest(session, project_id)
    subtitle = SubtitlePublicService().latest(session, project_id)
    return AudioSubtitleResponse(
        data=AudioSubtitleData(
            voice=VoiceData(run=voice_run_data(voice.run, voice.audio_url) if voice.run else None),
            subtitle=subtitle_data(subtitle).data,
        ),
        request_id=get_request_id(),
    )


@router.get("", response_model=AudioSubtitleResponse)
def get_audio_subtitle(project_id: str, session: Session = Depends(get_session)) -> AudioSubtitleResponse:
    return _response(session, project_id)


@router.post("/confirm", response_model=AudioSubtitleResponse)
def confirm_audio_subtitle(project_id: str, session: Session = Depends(get_session)) -> AudioSubtitleResponse:
    voice = VoicePublicService().latest(session, project_id).run
    subtitle = SubtitlePublicService().latest(session, project_id)
    if voice is None or subtitle is None:
        from onetake_api.modules.voice.service import VoiceNotFoundError
        raise VoiceNotFoundError("配音或字幕不存在")
    VoicePublicService().confirm(session, project_id)
    SubtitlePublicService().confirm(session, project_id)
    PipelinePublicService().mark_audio_subtitle_confirmed(session, project_id)
    session.commit()
    return _response(session, project_id)
