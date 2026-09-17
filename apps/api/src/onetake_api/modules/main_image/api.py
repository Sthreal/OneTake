from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onetake_api.modules.main_image.domain import MainImageVersion
from onetake_api.modules.main_image.public import MainImagePublicService
from onetake_api.modules.main_image.service import MainImageView
from onetake_api.platform.database import get_session
from onetake_api.platform.request_context import get_request_id

router = APIRouter(prefix="/api/v1/projects/{project_id}/main-image", tags=["main-image"])


class MainImageVersionData(BaseModel):
    version_id: str
    project_id: str
    source_asset_id: str
    status: str
    png_url: str | None
    jpg_url: str | None
    png_width: int | None
    png_height: int | None
    jpg_width: int | None
    jpg_height: int | None
    jpg_size_bytes: int | None
    product_ratio: float | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    confirmed_at: datetime | None


class MainImageData(BaseModel):
    version: MainImageVersionData | None


class MainImageResponse(BaseModel):
    data: MainImageData
    request_id: str


def _data(view: MainImageView | None) -> MainImageData:
    if view is None:
        return MainImageData(version=None)
    version: MainImageVersion = view.version
    return MainImageData(
        version=MainImageVersionData(
            version_id=version.id,
            project_id=version.project_id,
            source_asset_id=version.source_asset_id,
            status=version.status,
            png_url=view.png_url,
            jpg_url=view.jpg_url,
            png_width=version.png_width,
            png_height=version.png_height,
            jpg_width=version.jpg_width,
            jpg_height=version.jpg_height,
            jpg_size_bytes=version.jpg_size_bytes,
            product_ratio=version.product_ratio,
            error_code=version.error_code,
            created_at=version.created_at,
            updated_at=version.updated_at,
            completed_at=version.completed_at,
            confirmed_at=version.confirmed_at,
        )
    )


@router.post("", response_model=MainImageResponse, status_code=status.HTTP_202_ACCEPTED)
def request_main_image(project_id: str, session: Session = Depends(get_session)) -> MainImageResponse:
    view = MainImagePublicService().request(session, project_id)
    return MainImageResponse(data=_data(view), request_id=get_request_id())


@router.get("", response_model=MainImageResponse)
def get_main_image(project_id: str, session: Session = Depends(get_session)) -> MainImageResponse:
    view = MainImagePublicService().latest(session, project_id)
    return MainImageResponse(data=_data(view), request_id=get_request_id())


@router.post("/confirm", response_model=MainImageResponse)
def confirm_main_image(project_id: str, session: Session = Depends(get_session)) -> MainImageResponse:
    view = MainImagePublicService().confirm(session, project_id)
    return MainImageResponse(data=_data(view), request_id=get_request_id())
