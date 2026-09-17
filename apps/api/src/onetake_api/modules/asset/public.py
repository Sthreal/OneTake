from __future__ import annotations

from sqlalchemy.orm import Session

from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.modules.asset.application.commands import (
    CompleteUploadCommand,
    PresignUploadCommand,
)
from onetake_api.modules.asset.application.queries import ListAssetsQuery
from onetake_api.modules.asset.application.service import AssetApplicationService, PresignUploadResult
from onetake_api.modules.asset.domain.model import Asset


class AssetPublicService:
    def __init__(self) -> None:
        self._service = AssetApplicationService()

    def presign_upload(
        self,
        session: Session,
        *,
        project_id: str,
        command: PresignUploadCommand,
        storage: ObjectStoragePublicService,
    ) -> PresignUploadResult:
        return self._service.presign_upload(
            session,
            project_id=project_id,
            command=command,
            storage=storage,
        )

    def complete_upload(
        self,
        session: Session,
        *,
        project_id: str,
        asset_id: str,
        command: CompleteUploadCommand,
        storage: ObjectStoragePublicService,
    ) -> Asset:
        return self._service.complete_upload(
            session,
            project_id=project_id,
            asset_id=asset_id,
            command=command,
            storage=storage,
        )

    def list_assets(self, session: Session, *, project_id: str) -> list[Asset]:
        return self._service.list_assets(session, ListAssetsQuery(project_id=project_id))