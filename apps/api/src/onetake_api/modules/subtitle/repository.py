from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from onetake_api.modules.subtitle.domain import SubtitleVersion
from onetake_api.platform.database import Base


class SubtitleVersionModel(Base):
    __tablename__ = "versions"
    __table_args__ = {"schema": "subtitle"}

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    script_version_id: Mapped[str] = mapped_column(String(40), nullable=False)
    voice_run_id: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    language: Mapped[str] = mapped_column(String(20), nullable=False)
    segments: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    srt_object_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def _to_domain(model: SubtitleVersionModel) -> SubtitleVersion:
    return SubtitleVersion(
        id=model.id,
        project_id=model.project_id,
        script_version_id=model.script_version_id,
        voice_run_id=model.voice_run_id,
        status=model.status,
        enabled=model.enabled,
        language=model.language,
        segments=list(model.segments),
        srt_object_key=model.srt_object_key,
        error_code=model.error_code,
        created_at=model.created_at,
        updated_at=model.updated_at,
        completed_at=model.completed_at,
        confirmed_at=model.confirmed_at,
    )


class SubtitleRepository:
    def add(self, session: Session, version: SubtitleVersion) -> None:
        session.add(SubtitleVersionModel(**version.__dict__))

    def get(self, session: Session, version_id: str) -> SubtitleVersion | None:
        model = session.get(SubtitleVersionModel, version_id)
        return _to_domain(model) if model else None

    def latest(self, session: Session, project_id: str) -> SubtitleVersion | None:
        model = session.scalar(
            select(SubtitleVersionModel)
            .where(SubtitleVersionModel.project_id == project_id)
            .order_by(SubtitleVersionModel.created_at.desc())
        )
        return _to_domain(model) if model else None

    def update(self, session: Session, version: SubtitleVersion) -> None:
        model = session.get(SubtitleVersionModel, version.id)
        if model is None:
            return
        model.status = version.status
        model.segments = list(version.segments)
        model.srt_object_key = version.srt_object_key
        model.error_code = version.error_code
        model.updated_at = version.updated_at
        model.completed_at = version.completed_at
        model.confirmed_at = version.confirmed_at
