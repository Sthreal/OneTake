from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from onetake_api.modules.voice.domain import VoiceRun
from onetake_api.platform.database import Base


class VoiceRunModel(Base):
    __tablename__ = "runs"
    __table_args__ = {"schema": "voice"}

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    script_version_id: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    provider: Mapped[str] = mapped_column(String(60), nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    voice_id: Mapped[str] = mapped_column(String(80), nullable=False)
    language: Mapped[str] = mapped_column(String(20), nullable=False)
    speed: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(String(1200), nullable=False)
    audio_object_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    audio_mime_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    timestamps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def _to_domain(model: VoiceRunModel) -> VoiceRun:
    return VoiceRun(
        id=model.id,
        project_id=model.project_id,
        script_version_id=model.script_version_id,
        status=model.status,
        enabled=model.enabled,
        provider=model.provider,
        model=model.model,
        voice_id=model.voice_id,
        language=model.language,
        speed=model.speed,
        text=model.text,
        audio_object_key=model.audio_object_key,
        audio_mime_type=model.audio_mime_type,
        duration_seconds=model.duration_seconds,
        timestamps=list(model.timestamps),
        error_code=model.error_code,
        created_at=model.created_at,
        updated_at=model.updated_at,
        completed_at=model.completed_at,
    )


class VoiceRepository:
    def add(self, session: Session, run: VoiceRun) -> None:
        session.add(VoiceRunModel(**run.__dict__))

    def get(self, session: Session, run_id: str) -> VoiceRun | None:
        model = session.get(VoiceRunModel, run_id)
        return _to_domain(model) if model else None

    def latest(self, session: Session, project_id: str) -> VoiceRun | None:
        model = session.scalar(
            select(VoiceRunModel)
            .where(VoiceRunModel.project_id == project_id)
            .order_by(VoiceRunModel.created_at.desc())
        )
        return _to_domain(model) if model else None

    def update(self, session: Session, run: VoiceRun) -> None:
        model = session.get(VoiceRunModel, run.id)
        if model is None:
            return
        model.status = run.status
        model.audio_object_key = run.audio_object_key
        model.audio_mime_type = run.audio_mime_type
        model.duration_seconds = run.duration_seconds
        model.timestamps = list(run.timestamps)
        model.error_code = run.error_code
        model.updated_at = run.updated_at
        model.completed_at = run.completed_at
