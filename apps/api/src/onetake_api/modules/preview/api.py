"""预览片 HTTP 入口（S12 提交 3）。

两个端点，都不产生费用：`POST` 生成/复用（幂等），`GET` 取签名 URL（复用既有过期机制）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onetake_api.config import get_settings
from onetake_api.integrations.object_storage.dependencies import get_object_storage
from onetake_api.modules.preview.domain import PreviewDisabledError
from onetake_api.modules.preview.public import PreviewPublicService
from onetake_api.platform.database import get_session
from onetake_api.platform.request_context import get_request_id

router = APIRouter(prefix="/api/v1/projects/{project_id}/preview", tags=["preview"])

PREVIEW_URL_SECONDS = 60 * 60


class PreviewData(BaseModel):
    plan_id: str
    video_url: str
    width: int
    height: int
    fps: int
    duration_seconds: float
    size_bytes: int
    cached: bool
    base_source: str
    audio_source: str


class PreviewResponse(BaseModel):
    data: PreviewData
    request_id: str


def _data(artifact, *, url: str) -> PreviewData:
    return PreviewData(
        plan_id=artifact.plan_id,
        video_url=url,
        width=artifact.width,
        height=artifact.height,
        fps=artifact.fps,
        duration_seconds=artifact.duration_seconds,
        size_bytes=artifact.size_bytes,
        cached=artifact.cached,
        base_source=artifact.base_source,
        audio_source=artifact.audio_source,
    )


def _require_enabled() -> None:
    if not get_settings().preview_enabled:
        raise PreviewDisabledError("预览能力已被配置关闭（PREVIEW_ENABLED=false）")


@router.post("", response_model=PreviewResponse)
def build_preview(
    project_id: str,
    force: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> PreviewResponse:
    """生成（或命中缓存复用）一版廉价预览片。**全程零付费**：不碰 6 个付费端点。"""
    _require_enabled()
    artifact = PreviewPublicService().build_preview(session, project_id, force=force)
    url = get_object_storage().create_get_url(object_key=artifact.object_key, expires_seconds=PREVIEW_URL_SECONDS).url
    return PreviewResponse(data=_data(artifact, url=url), request_id=get_request_id())


@router.get("", response_model=PreviewResponse)
def get_preview(project_id: str, session: Session = Depends(get_session)) -> PreviewResponse:
    _require_enabled()
    artifact = PreviewPublicService().latest(session, project_id)
    url = get_object_storage().create_get_url(object_key=artifact.object_key, expires_seconds=PREVIEW_URL_SECONDS).url
    return PreviewResponse(data=_data(artifact, url=url), request_id=get_request_id())
