from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, StringConstraints
from sqlalchemy.orm import Session
from typing_extensions import Annotated

from onetake_api.config import get_settings
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.platform.database import get_session
from onetake_api.platform.request_context import get_request_id

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])

ProductName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
ProductNote = Annotated[str, StringConstraints(strip_whitespace=True, max_length=240)]


class ProjectCreateRequest(BaseModel):
    product_name: ProductName
    product_note: ProductNote | None = None


class ProjectData(BaseModel):
    project_id: str
    product_name: str
    product_note: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class ProjectResponse(BaseModel):
    data: ProjectData
    request_id: str


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreateRequest,
    session: Session = Depends(get_session),
) -> ProjectResponse:
    settings = get_settings()
    project = ProjectPublicService(ttl_hours=settings.project_ttl_hours).create_project(
        session,
        product_name=payload.product_name,
        product_note=payload.product_note,
    )
    return ProjectResponse(
        data=ProjectData(
            project_id=project.id,
            product_name=project.product_name,
            product_note=project.product_note,
            status=project.status,
            created_at=project.created_at,
            updated_at=project.updated_at,
        ),
        request_id=get_request_id(),
    )


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: str,
    session: Session = Depends(get_session),
) -> ProjectResponse:
    settings = get_settings()
    project = ProjectPublicService(ttl_hours=settings.project_ttl_hours).get_project(
        session,
        project_id=project_id,
    )
    return ProjectResponse(
        data=ProjectData(
            project_id=project.id,
            product_name=project.product_name,
            product_note=project.product_note,
            status=project.status,
            created_at=project.created_at,
            updated_at=project.updated_at,
        ),
        request_id=get_request_id(),
    )