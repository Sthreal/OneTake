from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from onetake_api.modules.asset.domain.model import Asset
from onetake_api.platform.database import Base


class AssetModel(Base):
    __tablename__ = "assets"
    __table_args__ = (
        UniqueConstraint("project_id", "sha256", name="uq_asset_project_sha256"),
        {"schema": "asset"},
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(50), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def _to_domain(model: AssetModel) -> Asset:
    return Asset(
        id=model.id,
        project_id=model.project_id,
        object_key=model.object_key,
        original_filename=model.original_filename,
        mime_type=model.mime_type,
        size_bytes=model.size_bytes,
        width=model.width,
        height=model.height,
        sha256=model.sha256,
        status=model.status,
        created_at=model.created_at,
        updated_at=model.updated_at,
        completed_at=model.completed_at,
    )


class SqlAlchemyAssetRepository:
    def add(self, session: Session, asset: Asset) -> None:
        session.add(
            AssetModel(
                id=asset.id,
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
        )

    def get(self, session: Session, asset_id: str) -> Asset | None:
        model = session.get(AssetModel, asset_id)
        return _to_domain(model) if model else None

    def update(self, session: Session, asset: Asset) -> None:
        model = session.get(AssetModel, asset.id)
        if model is None:
            return
        model.original_filename = asset.original_filename
        model.mime_type = asset.mime_type
        model.size_bytes = asset.size_bytes
        model.width = asset.width
        model.height = asset.height
        model.sha256 = asset.sha256
        model.status = asset.status
        model.updated_at = asset.updated_at
        model.completed_at = asset.completed_at

    def list_by_project(self, session: Session, project_id: str) -> list[Asset]:
        models = session.scalars(
            select(AssetModel)
            .where(AssetModel.project_id == project_id)
            .order_by(AssetModel.created_at.asc())
        ).all()
        return [_to_domain(model) for model in models]

    def count_by_project(self, session: Session, project_id: str) -> int:
        return int(
            session.scalar(
                select(func.count())
                .select_from(AssetModel)
                .where(AssetModel.project_id == project_id)
            )
            or 0
        )

    def find_by_sha256(
        self,
        session: Session,
        project_id: str,
        sha256: str,
        exclude_asset_id: str | None = None,
    ) -> Asset | None:
        statement = select(AssetModel).where(
            AssetModel.project_id == project_id,
            AssetModel.sha256 == sha256,
        )
        if exclude_asset_id:
            statement = statement.where(AssetModel.id != exclude_asset_id)
        model = session.scalar(statement)
        return _to_domain(model) if model else None