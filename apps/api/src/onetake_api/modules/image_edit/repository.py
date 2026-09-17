from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from onetake_api.modules.image_edit.domain import ImageEditRun
from onetake_api.platform.database import Base


class ImageEditRunModel(Base):
    __tablename__ = "runs"
    __table_args__ = {"schema": "image_edit"}

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    main_image_version_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source_asset_id: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(60), nullable=False)
    source_object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    output_object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    source_mime_type: Mapped[str] = mapped_column(String(50), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def _to_domain(model: ImageEditRunModel) -> ImageEditRun:
    return ImageEditRun(
        id=model.id,
        project_id=model.project_id,
        main_image_version_id=model.main_image_version_id,
        source_asset_id=model.source_asset_id,
        status=model.status,
        provider=model.provider,
        source_object_key=model.source_object_key,
        output_object_key=model.output_object_key,
        source_mime_type=model.source_mime_type,
        size_bytes=model.size_bytes,
        error_code=model.error_code,
        created_at=model.created_at,
        updated_at=model.updated_at,
        completed_at=model.completed_at,
    )


class ImageEditRepository:
    def add(self, session: Session, run: ImageEditRun) -> None:
        session.add(ImageEditRunModel(**run.__dict__))

    def get(self, session: Session, run_id: str) -> ImageEditRun | None:
        model = session.get(ImageEditRunModel, run_id)
        return _to_domain(model) if model else None

    def update(self, session: Session, run: ImageEditRun) -> None:
        model = session.get(ImageEditRunModel, run.id)
        if model is None:
            return
        model.status = run.status
        model.output_object_key = run.output_object_key
        model.size_bytes = run.size_bytes
        model.error_code = run.error_code
        model.updated_at = run.updated_at
        model.completed_at = run.completed_at

    def latest_for_version(self, session: Session, version_id: str) -> ImageEditRun | None:
        model = session.scalar(
            select(ImageEditRunModel)
            .where(ImageEditRunModel.main_image_version_id == version_id)
            .order_by(ImageEditRunModel.created_at.desc())
        )
        return _to_domain(model) if model else None
