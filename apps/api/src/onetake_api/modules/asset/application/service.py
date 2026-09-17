from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime
from io import BytesIO

from PIL import Image, UnidentifiedImageError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.modules.asset.adapters.sqlalchemy_repository import SqlAlchemyAssetRepository
from onetake_api.modules.asset.application.commands import (
    CompleteUploadCommand,
    PresignUploadCommand,
)
from onetake_api.modules.asset.application.queries import ListAssetsQuery
from onetake_api.modules.asset.domain.errors import (
    AssetDuplicateError,
    AssetNotFoundError,
    AssetNotUploadedError,
    AssetStateError,
    AssetValidationError,
)
from onetake_api.modules.asset.domain.model import (
    ASSET_STATUS_PENDING,
    ASSET_STATUS_READY,
    MAX_ASSETS_PER_PROJECT,
    MAX_FILE_SIZE_BYTES,
    PIL_FORMAT_TO_MIME,
    Asset,
    create_pending_asset,
    extension_for_mime_type,
    normalize_mime_type,
    normalize_sha256,
    validate_image_metadata,
)
from onetake_api.modules.outbox.public import OutboxPublicService
from onetake_api.modules.pipeline.public import PipelinePublicService
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.platform.clock import SystemClock
from onetake_api.platform.ids import new_id

PRESIGN_EXPIRES_SECONDS = 15 * 60


@dataclass(frozen=True)
class PresignUploadResult:
    asset: Asset
    upload_url: str
    expires_at: datetime
    required_headers: dict[str, str]


class AssetApplicationService:
    def __init__(self) -> None:
        self._repository = SqlAlchemyAssetRepository()
        self._clock = SystemClock()
        self._projects = ProjectPublicService()

    def presign_upload(
        self,
        session: Session,
        *,
        project_id: str,
        command: PresignUploadCommand,
        storage: ObjectStoragePublicService,
    ) -> PresignUploadResult:
        project = self._projects.get_project(session, project_id=project_id)
        now = self._clock.now()
        if project.expires_at <= now:
            raise AssetValidationError("项目已过期")

        if self._repository.count_by_project(session, project_id) >= MAX_ASSETS_PER_PROJECT:
            raise AssetValidationError("同一项目最多上传 5 张图片")

        filename = command.original_filename.strip()
        if not filename:
            raise AssetValidationError("文件名不能为空")
        if len(filename) > 255:
            raise AssetValidationError("文件名不能超过 255 个字符")

        validate_image_metadata(
            mime_type=command.mime_type,
            size_bytes=command.size_bytes,
            width=command.width,
            height=command.height,
        )
        client_sha = normalize_sha256(command.sha256) if command.sha256 else None
        if client_sha and self._repository.find_by_sha256(session, project_id, client_sha):
            raise AssetDuplicateError("该图片已存在于当前项目")

        asset_id = new_id("ast")
        mime_type = normalize_mime_type(command.mime_type)
        extension = extension_for_mime_type(mime_type)
        object_key = f"projects/{project_id}/assets/{asset_id}/original.{extension}"
        asset = create_pending_asset(
            asset_id=asset_id,
            project_id=project_id,
            object_key=object_key,
            original_filename=filename,
            mime_type=mime_type,
            size_bytes=command.size_bytes,
            width=command.width,
            height=command.height,
            sha256=client_sha,
            now=now,
        )
        self._repository.add(session, asset)
        try:
            session.flush()
        except IntegrityError as exc:
            raise AssetDuplicateError("该图片已存在于当前项目") from exc

        upload = storage.create_put_url(
            object_key=object_key,
            mime_type=mime_type,
            expires_seconds=PRESIGN_EXPIRES_SECONDS,
        )
        return PresignUploadResult(
            asset=asset,
            upload_url=upload.url,
            expires_at=upload.expires_at,
            required_headers=upload.headers,
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
        project = self._projects.get_project(session, project_id=project_id)
        if project.expires_at <= self._clock.now():
            raise AssetValidationError("项目已过期")
        asset = self._repository.get(session, asset_id)
        if asset is None or asset.project_id != project_id:
            raise AssetNotFoundError("素材不存在")
        if asset.status != ASSET_STATUS_PENDING:
            raise AssetStateError("素材当前状态不允许完成上传")

        object_info = storage.stat_object(object_key=asset.object_key)
        if object_info is None:
            raise AssetNotUploadedError("尚未检测到上传的图片")
        if object_info.size != command.size_bytes:
            raise AssetValidationError("上传文件大小与登记信息不一致")

        content = bytearray()
        for chunk in storage.read_object(object_key=asset.object_key):
            content.extend(chunk)
            if len(content) > MAX_FILE_SIZE_BYTES:
                raise AssetValidationError("单张图片不能超过 10 MB")

        actual_size = len(content)
        if actual_size != object_info.size:
            raise AssetValidationError("读取到的文件大小与对象存储不一致")

        actual_sha256 = hashlib.sha256(content).hexdigest()
        declared_sha256 = normalize_sha256(command.sha256)
        if actual_sha256 != declared_sha256:
            raise AssetValidationError("文件 SHA-256 校验失败")

        try:
            with Image.open(BytesIO(content)) as image:
                image.verify()
                detected_format = (image.format or "").upper()
                actual_width, actual_height = image.size
        except (UnidentifiedImageError, OSError) as exc:
            raise AssetValidationError("文件不是有效图片") from exc

        detected_mime = PIL_FORMAT_TO_MIME.get(detected_format)
        if detected_mime is None:
            raise AssetValidationError("仅支持 JPG、PNG 和 WebP")
        expected_mime = normalize_mime_type(command.mime_type)
        if detected_mime != expected_mime:
            raise AssetValidationError("图片真实格式与声明格式不一致")
        if actual_width != command.width or actual_height != command.height:
            raise AssetValidationError("图片真实尺寸与声明尺寸不一致")

        validate_image_metadata(
            mime_type=detected_mime,
            size_bytes=actual_size,
            width=actual_width,
            height=actual_height,
        )
        duplicate = self._repository.find_by_sha256(
            session,
            project_id,
            actual_sha256,
            exclude_asset_id=asset.id,
        )
        if duplicate is not None:
            raise AssetDuplicateError("该图片已存在于当前项目")

        now = self._clock.now()
        completed = replace(
            asset,
            original_filename=command.original_filename.strip(),
            mime_type=detected_mime,
            size_bytes=actual_size,
            width=actual_width,
            height=actual_height,
            sha256=actual_sha256,
            status=ASSET_STATUS_READY,
            updated_at=now,
            completed_at=now,
        )
        self._repository.update(session, completed)
        PipelinePublicService().mark_assets_ready(session, project_id)
        OutboxPublicService().enqueue(
            session,
            event_name="AssetRegistered",
            aggregate_type="asset",
            aggregate_id=asset.id,
            occurred_at=now,
            payload={
                "asset_id": asset.id,
                "project_id": project_id,
                "object_key": asset.object_key,
                "mime_type": detected_mime,
                "size_bytes": actual_size,
                "width": actual_width,
                "height": actual_height,
                "sha256": actual_sha256,
            },
        )
        try:
            session.flush()
        except IntegrityError as exc:
            raise AssetDuplicateError("该图片已存在于当前项目") from exc
        return completed

    def get_asset(self, session: Session, *, asset_id: str) -> Asset | None:
        return self._repository.get(session, asset_id)

    def list_assets(self, session: Session, query: ListAssetsQuery) -> list[Asset]:
        self._projects.get_project(session, project_id=query.project_id)
        return self._repository.list_by_project(session, query.project_id)
