from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from onetake_api.modules.video_plan.domain import VideoPlan
from onetake_api.modules.video_plan.public import VideoPlanPublicService
from onetake_api.modules.video_plan.service import VideoView
from onetake_api.platform.database import get_session
from onetake_api.platform.request_context import get_request_id

router = APIRouter(prefix="/api/v1/projects/{project_id}", tags=["video"])


class CreateVideoPlanRequest(BaseModel):
    mode: str = Field(pattern=r"^(avatar|product)$")
    template_id: str | None = Field(default=None, max_length=40)


class VideoPlanData(BaseModel):
    plan_id: str
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
    provider: str
    error_code: str | None
    video_url: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class VideoData(BaseModel):
    plan: VideoPlanData | None


class VideoResponse(BaseModel):
    data: VideoData
    request_id: str


def _data(plan: VideoPlan | None, video_url: str | None) -> VideoData:
    return VideoData(plan=VideoPlanData(
        plan_id=plan.id, project_id=plan.project_id, mode=plan.mode, template_id=plan.template_id,
        status=plan.status, duration_seconds=plan.duration_seconds, width=plan.width, height=plan.height,
        fps=plan.fps, voice_enabled=plan.voice_enabled, subtitle_enabled=plan.subtitle_enabled,
        provider=plan.provider, error_code=plan.error_code, video_url=video_url, created_at=plan.created_at,
        updated_at=plan.updated_at, completed_at=plan.completed_at,
    ) if plan else None)


def _response(view: VideoView) -> VideoResponse:
    return VideoResponse(data=_data(view.plan, view.video_url), request_id=get_request_id())


@router.post("/video-plan", response_model=VideoResponse, status_code=status.HTTP_201_CREATED)
def create_video_plan(project_id: str, payload: CreateVideoPlanRequest, session: Session = Depends(get_session)) -> VideoResponse:
    return _response(VideoPlanPublicService().create_plan(session, project_id=project_id, mode=payload.mode, template_id=payload.template_id))


@router.get("/video", response_model=VideoResponse)
def get_video(project_id: str, session: Session = Depends(get_session)) -> VideoResponse:
    return _response(VideoPlanPublicService().latest(session, project_id))


@router.post("/video", response_model=VideoResponse, status_code=status.HTTP_202_ACCEPTED)
def request_video(project_id: str, session: Session = Depends(get_session)) -> VideoResponse:
    return _response(VideoPlanPublicService().request_video(session, project_id))


@router.post("/compose", response_model=VideoResponse, status_code=status.HTTP_202_ACCEPTED)
def request_compose(project_id: str, session: Session = Depends(get_session)) -> VideoResponse:
    return _response(VideoPlanPublicService().request_video(session, project_id))
