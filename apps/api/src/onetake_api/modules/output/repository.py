from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from onetake_api.modules.output.domain import OutputArtifact
from onetake_api.platform.database import Base


class OutputArtifactModel(Base):
    __tablename__ = "artifacts"
    __table_args__ = {"schema": "output"}

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(80), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    video_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    video_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    video_codec: Mapped[str | None] = mapped_column(String(30), nullable=True)
    audio_codec: Mapped[str | None] = mapped_column(String(30), nullable=True)


def _to_domain(model: OutputArtifactModel) -> OutputArtifact:
    return OutputArtifact(model.id, model.project_id, model.kind, model.object_key, model.mime_type, model.size_bytes, model.duration_seconds, model.created_at, model.expires_at, model.video_width, model.video_height, model.fps, model.video_codec, model.audio_codec)


class OutputRepository:
    def add(self, session: Session, artifact: OutputArtifact) -> None:
        session.add(OutputArtifactModel(**artifact.__dict__))

    def latest(self, session: Session, project_id: str) -> OutputArtifact | None:
        model = session.scalar(select(OutputArtifactModel).where(OutputArtifactModel.project_id == project_id).order_by(OutputArtifactModel.created_at.desc()))
        return _to_domain(model) if model else None
