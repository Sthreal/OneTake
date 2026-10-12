from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from onetake_api.modules.video_plan.domain import VideoPlan
from onetake_api.modules.video_plan.estimate import VideoGenerationEstimate
from onetake_api.modules.video_plan.public import VideoPlanPublicService
from onetake_api.modules.video_plan.segment_domain import VideoSegment, VideoSegmentCandidate
from onetake_api.modules.video_plan.segment_public import VideoSegmentPublicService
from onetake_api.modules.video_plan.segment_service import SegmentValidationError
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
    batch_status: str
    batch_stop_requested: bool


class VideoData(BaseModel):
    plan: VideoPlanData | None


class VideoResponse(BaseModel):
    data: VideoData
    request_id: str


class VideoEstimateData(BaseModel):
    plan_id: str
    mode: str
    template_id: str | None
    duration_seconds: float
    is_paid: bool
    wan_clip_count: int
    wan_generated_seconds: int
    qwen_image_edit_calls: int
    shotstack_renders: int
    estimated_wan_cost: float
    estimated_known_cost: float
    estimated_cost_max: float | None
    currency: str
    estimated_minutes: float
    confirmation_threshold: float
    requires_confirmation: bool
    missing_price_config: list[str]
    price_notes: list[str]


class VideoEstimateResponse(BaseModel):
    data: VideoEstimateData
    request_id: str


def _data(plan: VideoPlan | None, video_url: str | None) -> VideoData:
    return VideoData(plan=VideoPlanData(
        plan_id=plan.id, project_id=plan.project_id, mode=plan.mode, template_id=plan.template_id,
        status=plan.status, duration_seconds=plan.duration_seconds, width=plan.width, height=plan.height,
        fps=plan.fps, voice_enabled=plan.voice_enabled, subtitle_enabled=plan.subtitle_enabled,
        provider=plan.provider, error_code=plan.error_code, video_url=video_url, created_at=plan.created_at,
        updated_at=plan.updated_at, completed_at=plan.completed_at, batch_status=plan.batch_status, batch_stop_requested=plan.batch_stop_requested,
    ) if plan else None)


def _response(view: VideoView) -> VideoResponse:
    return VideoResponse(data=_data(view.plan, view.video_url), request_id=get_request_id())


@router.get("/video-plan/{plan_id}/estimate", response_model=VideoEstimateResponse)
def estimate_video(project_id: str, plan_id: str, session: Session = Depends(get_session)) -> VideoEstimateResponse:
    estimate: VideoGenerationEstimate = VideoPlanPublicService().estimate(session, project_id=project_id, plan_id=plan_id)
    return VideoEstimateResponse(data=VideoEstimateData(**asdict(estimate)), request_id=get_request_id())


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


class SegmentCandidateData(BaseModel):
    candidate_id: str
    segment_id: str
    order_index: int
    status: str
    provider: str
    anchor_source: str
    video_url: str | None
    tail_frame_url: str | None
    head_frame_url: str | None
    anchor_candidate_id: str | None
    duration_seconds: float | None
    width: int | None
    height: int | None
    fps: int | None
    error_code: str | None
    created_at: datetime


class SegmentData(BaseModel):
    segment_id: str
    plan_id: str
    order_index: int
    scene_id: str
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    status: str
    accepted_candidate_id: str | None
    last_error: str | None
    anchor_source: str | None
    candidates: list[SegmentCandidateData]


class SegmentListData(BaseModel):
    plan_id: str | None
    segments: list[SegmentData]


class SegmentListResponse(BaseModel):
    data: SegmentListData
    request_id: str


def _candidate_url(object_key: str | None) -> str | None:
    if not object_key:
        return None
    try:
        from onetake_api.integrations.object_storage.dependencies import get_object_storage
        return get_object_storage().create_get_url(object_key=object_key, expires_seconds=3600).url
    except Exception:
        return None


def _candidate_data(candidate: VideoSegmentCandidate) -> SegmentCandidateData:
    return SegmentCandidateData(
        candidate_id=candidate.id, segment_id=candidate.segment_id, order_index=candidate.order_index,
        status=candidate.status, provider=candidate.provider, anchor_source=candidate.anchor_source,
        video_url=_candidate_url(candidate.video_object_key), tail_frame_url=_candidate_url(candidate.tail_frame_object_key),
        head_frame_url=_candidate_url(candidate.head_frame_object_key), anchor_candidate_id=candidate.anchor_candidate_id,
        duration_seconds=candidate.duration_seconds, width=candidate.width, height=candidate.height,
        fps=candidate.fps, error_code=candidate.error_code, created_at=candidate.created_at,
    )

def _segment_data(segment: VideoSegment) -> SegmentData:
    accepted = next((item for item in segment.candidates if item.id == segment.accepted_candidate_id), None)
    return SegmentData(
        segment_id=segment.id, plan_id=segment.plan_id, order_index=segment.order_index, scene_id=segment.scene_id,
        start_seconds=segment.start_seconds, end_seconds=segment.end_seconds, duration_seconds=segment.duration_seconds,
        status=segment.status, accepted_candidate_id=segment.accepted_candidate_id, last_error=segment.last_error,
        anchor_source=accepted.anchor_source if accepted else None,
        candidates=[_candidate_data(item) for item in segment.candidates],
    )


def _segment_response(project_id: str, plan_id: str | None, segments: list[VideoSegment]) -> SegmentListResponse:
    return SegmentListResponse(
        data=SegmentListData(plan_id=plan_id, segments=[_segment_data(item) for item in segments]),
        request_id=get_request_id(),
    )


@router.get("/video/segments", response_model=SegmentListResponse)
def list_video_segments(project_id: str, plan_id: str | None = None, session: Session = Depends(get_session)) -> SegmentListResponse:
    segments = VideoSegmentPublicService().materialize_segments(session, project_id=project_id, plan_id=plan_id)
    resolved_plan_id = segments[0].plan_id if segments else plan_id
    return _segment_response(project_id, resolved_plan_id, segments)


@router.post("/video/segments/{segment_id}/candidates", response_model=SegmentListResponse, status_code=status.HTTP_201_CREATED)
def generate_segment_candidate(project_id: str, segment_id: str, payload: dict | None = None, session: Session = Depends(get_session)) -> SegmentListResponse:
    seed = payload.get("seed") if isinstance(payload, dict) else None
    segments = VideoSegmentPublicService().generate_candidate(session, project_id=project_id, segment_id=segment_id, seed=seed)
    return _segment_response(project_id, segments[0].plan_id if segments else None, segments)


@router.post("/video/segments/{segment_id}/accept", response_model=SegmentListResponse)
def accept_segment_candidate(project_id: str, segment_id: str, payload: dict, session: Session = Depends(get_session)) -> SegmentListResponse:
    candidate_id = str(payload.get("candidate_id") or "")
    if not candidate_id:
        raise SegmentValidationError("缺少 candidate_id")
    segments = VideoSegmentPublicService().accept_candidate(session, project_id=project_id, candidate_id=candidate_id)
    return _segment_response(project_id, segments[0].plan_id if segments else None, segments)


@router.post("/video/segments/{segment_id}/reject", response_model=SegmentListResponse)
def reject_video_segment(project_id: str, segment_id: str, session: Session = Depends(get_session)) -> SegmentListResponse:
    segments = VideoSegmentPublicService().reject_segment(session, project_id=project_id, segment_id=segment_id)
    return _segment_response(project_id, segments[0].plan_id if segments else None, segments)


@router.post("/video/batch", response_model=VideoResponse, status_code=status.HTTP_202_ACCEPTED)
def start_video_batch(project_id: str, session: Session = Depends(get_session)) -> VideoResponse:
    plan = VideoSegmentPublicService().start_batch(session, project_id=project_id)
    return _response(VideoView(plan=plan, video_url=None))


@router.post("/video/batch/stop", response_model=VideoResponse)
def stop_video_batch(project_id: str, session: Session = Depends(get_session)) -> VideoResponse:
    plan = VideoSegmentPublicService().stop_batch(session, project_id=project_id)
    return _response(VideoView(plan=plan, video_url=None))
