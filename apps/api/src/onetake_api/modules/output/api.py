"""多平台导出（批次 6）：档位查询 + 导出（视频 / 封面预览）。

两条硬纪律：
1. **原片不覆盖**：导出件写到 `projects/<pid>/exports/<plan>/<profile>/` 下的**新 key**，成片对象一个字不动。
2. **交付门不放行就不给导**：复用交付门的**唯一判据** `download_allowed_for()`
   （与 `/output` 下载一致），没结论 / 有 fail / 有未确认 warn 一律 409，并说明卡在哪。
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Literal

from fastapi import APIRouter, Depends, status
from PIL import Image
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from onetake_api.config import get_settings
from onetake_api.integrations.media import export as export_media
from onetake_api.integrations.object_storage.dependencies import get_object_storage
from onetake_api.modules.output.repository import OutputRepository
from onetake_api.modules.output.profiles import list_export_profiles, resolve_export_profile
from onetake_api.modules.video_plan.gate import download_allowed_for
from onetake_api.modules.video_plan.public import VideoPlanPublicService
from onetake_api.platform.database import get_session
from onetake_api.platform.errors import DomainError
from onetake_api.platform.request_context import get_request_id

router = APIRouter(prefix="/api/v1/projects/{project_id}/output", tags=["output"])
export_router = APIRouter(prefix="/api/v1/projects/{project_id}/export", tags=["export"])

ARTIFACT_URL_SECONDS = 24 * 60 * 60
DEFAULT_COVER_SECONDS = 0.5


class ExportNotReadyError(DomainError):
    code = "EXPORT_NOT_READY"
    http_status = 409
    retryable = False


class ExportBlockedError(DomainError):
    code = "EXPORT_BLOCKED_BY_GATE"
    http_status = 409
    retryable = False


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


class ExportProfileData(BaseModel):
    key: str
    label: str
    width: int
    height: int
    strategy: str
    platforms: list[str]
    note: str


class ExportProfilesResponse(BaseModel):
    data: list[ExportProfileData]
    request_id: str


class ExportRequest(BaseModel):
    profile: str = "douyin"
    kind: Literal["video", "cover"] = "video"
    at_seconds: float | None = Field(default=None, ge=0)


class ExportReportData(BaseModel):
    """**实测**导出报告：尺寸/时长/码率都是量出来的，不是按参数推断的。"""

    profile: str
    profile_label: str
    kind: str
    strategy: str
    download_url: str
    expires_at: datetime
    width: int
    height: int
    duration_seconds: float
    size_bytes: int
    bitrate_kbps: int
    source_size_bytes: int
    source_bitrate_kbps: int
    has_audio: bool
    at_seconds: float | None = None


class ExportResponse(BaseModel):
    data: ExportReportData
    request_id: str


@router.get("", response_model=OutputResponse)
def get_output(project_id: str, session: Session = Depends(get_session)) -> OutputResponse:
    artifact = OutputRepository().latest(session, project_id)
    data = None
    if artifact:
        url = get_object_storage().create_get_url(object_key=artifact.object_key, expires_seconds=ARTIFACT_URL_SECONDS).url
        data = OutputData(artifact_id=artifact.id, kind=artifact.kind, mime_type=artifact.mime_type, size_bytes=artifact.size_bytes, duration_seconds=artifact.duration_seconds, download_url=url, expires_at=artifact.expires_at, video_width=artifact.video_width, video_height=artifact.video_height, fps=artifact.fps, video_codec=artifact.video_codec, audio_codec=artifact.audio_codec)
    return OutputResponse(data=data, request_id=get_request_id())


def _profile_data(profile) -> ExportProfileData:
    return ExportProfileData(
        key=profile.key, label=profile.label, width=profile.width, height=profile.height,
        strategy=profile.strategy, platforms=list(profile.platforms), note=profile.note,
    )


@export_router.get("/profiles", response_model=ExportProfilesResponse)
def get_export_profiles() -> ExportProfilesResponse:
    settings = get_settings()
    return ExportProfilesResponse(
        data=[_profile_data(profile) for profile in list_export_profiles(settings=settings)],
        request_id=get_request_id(),
    )


@export_router.post("", response_model=ExportResponse, status_code=status.HTTP_201_CREATED)
def create_export(
    project_id: str, payload: ExportRequest, session: Session = Depends(get_session)
) -> ExportResponse:
    settings = get_settings()
    plan = getattr(VideoPlanPublicService().latest(session, project_id), "plan", None)
    if plan is None or not plan.final_object_key:
        raise ExportNotReadyError("还没有成片，无法导出")
    allowed, reason = download_allowed_for(session, project_id)
    if not allowed:
        raise ExportBlockedError(reason or "交付门未放行")

    profile = resolve_export_profile(payload.profile, settings=settings)
    storage = get_object_storage()
    source = b"".join(storage.read_object(object_key=plan.final_object_key))
    source_measure = export_media.measure(source)
    base_key = f"projects/{project_id}/exports/{plan.id}/{profile.key}"

    if payload.kind == "cover":
        at_seconds = DEFAULT_COVER_SECONDS if payload.at_seconds is None else payload.at_seconds
        at_seconds = round(min(max(0.0, at_seconds), max(0.0, source_measure.duration_seconds - 0.05)), 3)
        content = export_media.export_frame(
            source_bytes=source, at_seconds=at_seconds, strategy=profile.strategy,
            width=profile.width, height=profile.height,
        )
        with Image.open(BytesIO(content)) as image:
            width, height = image.size
        object_key = f"{base_key}/cover-{int(at_seconds * 1000)}ms.png"
        mime_type, duration_seconds, has_audio = "image/png", 0.0, False
    else:
        content = export_media.export_video(
            source_bytes=source, strategy=profile.strategy,
            width=profile.width, height=profile.height, fps=plan.fps,
        )
        measured = export_media.measure(content)
        width, height = measured.width, measured.height
        duration_seconds, has_audio = measured.duration_seconds, measured.has_audio
        object_key = f"{base_key}/video.mp4"
        mime_type = "video/mp4"
        at_seconds = None

    storage.put_bytes(object_key=object_key, content=content, mime_type=mime_type)
    report = {
        "profile": profile.key, "kind": payload.kind, "strategy": profile.strategy,
        "width": width, "height": height, "duration_seconds": duration_seconds,
        "size_bytes": len(content), "has_audio": has_audio, "at_seconds": at_seconds,
        "source_size_bytes": len(source), "source_width": source_measure.width,
        "source_height": source_measure.height, "source_bitrate_kbps": source_measure.bitrate_kbps,
        "created_at": datetime.now(UTC).isoformat(),
    }
    storage.put_bytes(
        object_key=f"{base_key}/export-report.json",
        content=json.dumps(report, ensure_ascii=False, indent=1).encode("utf-8"),
        mime_type="application/json",
    )
    expires_at = datetime.now(UTC) + timedelta(seconds=ARTIFACT_URL_SECONDS)
    url = storage.create_get_url(object_key=object_key, expires_seconds=ARTIFACT_URL_SECONDS).url
    bitrate_kbps = 0 if duration_seconds <= 0 else int(round(len(content) * 8 / duration_seconds / 1000))
    return ExportResponse(
        data=ExportReportData(
            profile=profile.key, profile_label=profile.label, kind=payload.kind, strategy=profile.strategy,
            download_url=url, expires_at=expires_at, width=width, height=height,
            duration_seconds=duration_seconds, size_bytes=len(content), bitrate_kbps=bitrate_kbps,
            source_size_bytes=len(source), source_bitrate_kbps=source_measure.bitrate_kbps,
            has_audio=has_audio, at_seconds=at_seconds,
        ),
        request_id=get_request_id(),
    )