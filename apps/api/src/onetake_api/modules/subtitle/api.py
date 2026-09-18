from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from onetake_api.integrations.object_storage.dependencies import get_object_storage
from onetake_api.modules.subtitle.domain import SUBTITLE_READY, SubtitleVersion
from onetake_api.modules.subtitle.public import SubtitlePublicService
from onetake_api.modules.pipeline.public import PipelinePublicService
from onetake_api.modules.voice.public import VoicePublicService
from onetake_api.platform.database import get_session
from onetake_api.platform.queue import get_queue
from onetake_api.platform.request_context import get_request_id

router = APIRouter(prefix="/api/v1/projects/{project_id}/subtitle", tags=["subtitle"])


class SubtitleSegmentInput(BaseModel):
    index: int
    text: str = Field(min_length=1, max_length=120)


class SubtitleRequest(BaseModel):
    enabled: bool = True


class EditSubtitleRequest(BaseModel):
    segments: list[SubtitleSegmentInput] = Field(min_length=1, max_length=12)


class SubtitleVersionData(BaseModel):
    subtitle_id: str
    project_id: str
    script_version_id: str
    voice_run_id: str
    status: str
    enabled: bool
    language: str
    segments: list[dict]
    srt_url: str | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    confirmed_at: datetime | None


class SubtitleData(BaseModel):
    version: SubtitleVersionData | None


class SubtitleResponse(BaseModel):
    data: SubtitleData
    request_id: str


def _data(version: SubtitleVersion | None) -> SubtitleResponse:
    srt_url = None
    if version and version.srt_object_key:
        srt_url = get_object_storage().create_get_url(object_key=version.srt_object_key, expires_seconds=3600).url
    return SubtitleResponse(
        data=SubtitleData(
            version=SubtitleVersionData(
                subtitle_id=version.id,
                project_id=version.project_id,
                script_version_id=version.script_version_id,
                voice_run_id=version.voice_run_id,
                status=version.status,
                enabled=version.enabled,
                language=version.language,
                segments=version.segments,
                srt_url=srt_url,
                error_code=version.error_code,
                created_at=version.created_at,
                updated_at=version.updated_at,
                completed_at=version.completed_at,
                confirmed_at=version.confirmed_at,
            ) if version else None,
        ),
        request_id=get_request_id(),
    )


@router.get("", response_model=SubtitleResponse)
def get_subtitle(project_id: str, session: Session = Depends(get_session)) -> SubtitleResponse:
    return _data(SubtitlePublicService().latest(session, project_id))


@router.post("", response_model=SubtitleResponse, status_code=status.HTTP_202_ACCEPTED)
def request_subtitle(project_id: str, payload: SubtitleRequest, session: Session = Depends(get_session)) -> SubtitleResponse:
    voice = VoicePublicService().latest(session, project_id).run
    if voice is None or voice.status not in {"ready", "confirmed"}:
        return _data(SubtitlePublicService().latest(session, project_id))
    result = SubtitlePublicService().start(
        session,
        project_id=project_id,
        script_version_id=voice.script_version_id,
        voice_run_id=voice.id,
        enabled=payload.enabled,
        pipeline_run_id=PipelinePublicService().get_or_create(session, project_id).id,
    )
    session.commit()
    if result.job:
        get_queue("subtitle").enqueue("onetake_api.modules.subtitle.worker_tasks.run_subtitle_job", result.job.id, job_id=result.job.id, job_timeout=120)
    return _data(result.version)


@router.patch("", response_model=SubtitleResponse)
def edit_subtitle(project_id: str, payload: EditSubtitleRequest, session: Session = Depends(get_session)) -> SubtitleResponse:
    version = SubtitlePublicService().update_segments(session, project_id=project_id, segments=[item.model_dump() for item in payload.segments])
    return _data(version)
