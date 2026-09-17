from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from onetake_api.integrations.object_storage.dependencies import get_object_storage
from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.modules.asset.application.commands import (
    CompleteUploadCommand,
    PresignUploadCommand,
)
from onetake_api.modules.asset.domain.model import Asset
from onetake_api.modules.asset.public import AssetPublicService
from onetake_api.platform.database import get_session
from onetake_api.platform.request_context import get_request_id

router = APIRouter(prefix="/api/v1/projects/{project_id}/assets", tags=["assets"])


class PresignUploadRequest(BaseModel):
    original_filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=50)
    size_bytes: int = Field(gt=0, le=10 * 1024 * 1024)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")


class CompleteUploadRequest(BaseModel):
    original_filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=50)
    size_bytes: int = Field(gt=0, le=10 * 1024 * 1024)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")


class PresignUploadData(BaseModel):
    asset_id: str
    object_key: str
    upload_url: str
    expires_at: datetime
    required_headers: dict[str, str]


class PresignUploadResponse(BaseModel):
    data: PresignUploadData
    request_id: str


class AssetData(BaseModel):
    asset_id: str
    project_id: str
    object_key: str
    original_filename: str
    mime_type: str
    size_bytes: int
    width: int
    height: int
    sha256: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class AssetResponse(BaseModel):
    data: AssetData
    request_id: str


class AssetListResponse(BaseModel):
    data: list[AssetData]
    request_id: str


def _asset_data(asset: Asset) -> AssetData:
    return AssetData(
        asset_id=asset.id,
        project_id=asset.project_id,
        object_key=asset.object_key,
        original_filename=asset.original_filename,
        mime_type=asset.mime_type,
        size_bytes=asset.size_bytes,
        width=asset.width,
        height=asset.height,
        sha256=asset.sha256,
        status=asset.status,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
        completed_at=asset.completed_at,
    )


@router.post("/presign", response_model=PresignUploadResponse, status_code=status.HTTP_201_CREATED)
def presign_upload(
    project_id: str,
    payload: PresignUploadRequest,
    session: Session = Depends(get_session),
    storage: ObjectStoragePublicService = Depends(get_object_storage),
) -> PresignUploadResponse:
    result = AssetPublicService().presign_upload(
        session,
        project_id=project_id,
        command=PresignUploadCommand(
            original_filename=payload.original_filename,
            mime_type=payload.mime_type,
            size_bytes=payload.size_bytes,
            width=payload.width,
            height=payload.height,
            sha256=payload.sha256,
        ),
        storage=storage,
    )
    return PresignUploadResponse(
        data=PresignUploadData(
            asset_id=result.asset.id,
            object_key=result.asset.object_key,
            upload_url=result.upload_url,
            expires_at=result.expires_at,
            required_headers=result.required_headers,
        ),
        request_id=get_request_id(),
    )


@router.post("/{asset_id}/complete", response_model=AssetResponse)
def complete_upload(
    project_id: str,
    asset_id: str,
    payload: CompleteUploadRequest,
    session: Session = Depends(get_session),
    storage: ObjectStoragePublicService = Depends(get_object_storage),
) -> AssetResponse:
    asset = AssetPublicService().complete_upload(
        session,
        project_id=project_id,
        asset_id=asset_id,
        command=CompleteUploadCommand(
            original_filename=payload.original_filename,
            mime_type=payload.mime_type,
            size_bytes=payload.size_bytes,
            width=payload.width,
            height=payload.height,
            sha256=payload.sha256,
        ),
        storage=storage,
    )
    return AssetResponse(data=_asset_data(asset), request_id=get_request_id())


@router.get("", response_model=AssetListResponse)
def list_assets(
    project_id: str,
    session: Session = Depends(get_session),
) -> AssetListResponse:
    assets = AssetPublicService().list_assets(session, project_id=project_id)
    return AssetListResponse(
        data=[_asset_data(asset) for asset in assets],
        request_id=get_request_id(),
    )