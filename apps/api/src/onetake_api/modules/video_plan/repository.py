from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from onetake_api.modules.video_plan.domain import VideoPlan
from onetake_api.platform.database import Base


class VideoPlanModel(Base):
    __tablename__ = "plans"
    __table_args__ = {"schema": "video_plan"}

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    template_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    fps: Mapped[int] = mapped_column(Integer, nullable=False)
    voice_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    subtitle_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    main_image_object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    voice_object_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    subtitle_object_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    base_video_object_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    final_object_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    provider: Mapped[str] = mapped_column(String(60), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def _to_domain(model: VideoPlanModel) -> VideoPlan:
    return VideoPlan(
        id=model.id, project_id=model.project_id, mode=model.mode, template_id=model.template_id,
        status=model.status, duration_seconds=model.duration_seconds, width=model.width, height=model.height,
        fps=model.fps, voice_enabled=model.voice_enabled, subtitle_enabled=model.subtitle_enabled,
        main_image_object_key=model.main_image_object_key, voice_object_key=model.voice_object_key,
        subtitle_object_key=model.subtitle_object_key, base_video_object_key=model.base_video_object_key,
        final_object_key=model.final_object_key, provider=model.provider, error_code=model.error_code,
        created_at=model.created_at, updated_at=model.updated_at, completed_at=model.completed_at,
        confirmed_at=model.confirmed_at,
    )


class VideoPlanRepository:
    def add(self, session: Session, plan: VideoPlan) -> None:
        session.add(VideoPlanModel(**plan.__dict__))

    def get(self, session: Session, plan_id: str) -> VideoPlan | None:
        model = session.get(VideoPlanModel, plan_id)
        return _to_domain(model) if model else None

    def latest(self, session: Session, project_id: str) -> VideoPlan | None:
        model = session.scalar(select(VideoPlanModel).where(VideoPlanModel.project_id == project_id).order_by(VideoPlanModel.created_at.desc()))
        return _to_domain(model) if model else None

    def update(self, session: Session, plan: VideoPlan) -> None:
        model = session.get(VideoPlanModel, plan.id)
        if model is None:
            return
        model.status = plan.status
        model.base_video_object_key = plan.base_video_object_key
        model.final_object_key = plan.final_object_key
        model.error_code = plan.error_code
        model.updated_at = plan.updated_at
        model.completed_at = plan.completed_at
        model.confirmed_at = plan.confirmed_at
