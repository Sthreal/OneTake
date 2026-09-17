from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from onetake_api.modules.main_image.domain import MainImageVersion
from onetake_api.platform.database import Base


class MainImageVersionModel(Base):
    __tablename__ = "versions"
    __table_args__ = {"schema": "main_image"}

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source_asset_id: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    image_edit_run_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    matting_run_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    transparent_object_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    jpg_object_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    png_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    png_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    jpg_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    jpg_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    jpg_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def _to_domain(model: MainImageVersionModel) -> MainImageVersion:
    return MainImageVersion(
        id=model.id,
        project_id=model.project_id,
        source_asset_id=model.source_asset_id,
        status=model.status,
        image_edit_run_id=model.image_edit_run_id,
        matting_run_id=model.matting_run_id,
        transparent_object_key=model.transparent_object_key,
        jpg_object_key=model.jpg_object_key,
        png_width=model.png_width,
        png_height=model.png_height,
        jpg_width=model.jpg_width,
        jpg_height=model.jpg_height,
        jpg_size_bytes=model.jpg_size_bytes,
        product_ratio=model.product_ratio,
        error_code=model.error_code,
        created_at=model.created_at,
        updated_at=model.updated_at,
        completed_at=model.completed_at,
        confirmed_at=model.confirmed_at,
    )


class MainImageRepository:
    def add(self, session: Session, version: MainImageVersion) -> None:
        session.add(MainImageVersionModel(**version.__dict__))

    def get(self, session: Session, version_id: str) -> MainImageVersion | None:
        model = session.get(MainImageVersionModel, version_id)
        return _to_domain(model) if model else None

    def latest(self, session: Session, project_id: str) -> MainImageVersion | None:
        model = session.scalar(
            select(MainImageVersionModel)
            .where(MainImageVersionModel.project_id == project_id)
            .order_by(MainImageVersionModel.created_at.desc())
        )
        return _to_domain(model) if model else None

    def update(self, session: Session, version: MainImageVersion) -> None:
        model = session.get(MainImageVersionModel, version.id)
        if model is None:
            return
        model.status = version.status
        model.image_edit_run_id = version.image_edit_run_id
        model.matting_run_id = version.matting_run_id
        model.transparent_object_key = version.transparent_object_key
        model.jpg_object_key = version.jpg_object_key
        model.png_width = version.png_width
        model.png_height = version.png_height
        model.jpg_width = version.jpg_width
        model.jpg_height = version.jpg_height
        model.jpg_size_bytes = version.jpg_size_bytes
        model.product_ratio = version.product_ratio
        model.error_code = version.error_code
        model.updated_at = version.updated_at
        model.completed_at = version.completed_at
        model.confirmed_at = version.confirmed_at
