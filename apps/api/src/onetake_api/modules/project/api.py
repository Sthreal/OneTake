from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, StringConstraints
from sqlalchemy.orm import Session
from typing_extensions import Annotated

from onetake_api.config import get_settings
from onetake_api.integrations.object_storage.dependencies import get_object_storage
from onetake_api.modules.maintenance.service import MediaLifecycleService
from onetake_api.modules.project.domain.errors import ProjectValidationError
from onetake_api.modules.project.domain.model import Project
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.platform.database import get_session
from onetake_api.platform.request_context import get_request_id

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])

ProductName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
ProductNote = Annotated[str, StringConstraints(strip_whitespace=True, max_length=240)]


class ProjectCreateRequest(BaseModel):
    product_name: ProductName
    product_note: ProductNote | None = None


class ProjectUpdateRequest(BaseModel):
    product_name: ProductName | None = None
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


class ProjectListResponse(BaseModel):
    data: list[ProjectData]
    request_id: str


def _project_data(project: Project) -> ProjectData:
    return ProjectData(
        project_id=project.id,
        product_name=project.product_name,
        product_note=project.product_note,
        status=project.status,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


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
    return ProjectResponse(data=_project_data(project), request_id=get_request_id())


@router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: str,
    payload: ProjectUpdateRequest,
    session: Session = Depends(get_session),
) -> ProjectResponse:
    if not payload.model_fields_set:
        raise ProjectValidationError("至少提供一个需要更新的字段")
    if "product_name" in payload.model_fields_set and payload.product_name is None:
        raise ProjectValidationError("商品名称不能为空")
    project = ProjectPublicService().update_project(
        session,
        project_id=project_id,
        product_name=payload.product_name,
        product_note=payload.product_note,
        update_product_note="product_note" in payload.model_fields_set,
    )
    return ProjectResponse(data=_project_data(project), request_id=get_request_id())


@router.get("", response_model=ProjectListResponse)
def list_projects(
    limit: int = Query(default=20, ge=1, le=50),
    session: Session = Depends(get_session),
) -> ProjectListResponse:
    projects = ProjectPublicService().list_projects(session, limit=limit)
    return ProjectListResponse(
        data=[_project_data(project) for project in projects],
        request_id=get_request_id(),
    )


@router.delete("/{project_id}/media", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_media(
    project_id: str,
    session: Session = Depends(get_session),
    storage=Depends(get_object_storage),
) -> Response:
    MediaLifecycleService().delete_project_media(
        session,
        project_id=project_id,
        storage=storage,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    return ProjectResponse(data=_project_data(project), request_id=get_request_id())
