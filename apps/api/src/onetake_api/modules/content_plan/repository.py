from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from onetake_api.modules.content_plan.domain import ContentPlan, ContentScene, ContentVariant
from onetake_api.platform.database import Base


class ContentPlanModel(Base):
    __tablename__ = "plans"
    __table_args__ = {"schema": "content_plan"}

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    script_version_id: Mapped[str] = mapped_column(String(40), nullable=False)
    subtitle_version_id: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(60), nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    variants: Mapped[list] = mapped_column(JSON, nullable=False)
    selected_variant_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def _scene(data: dict) -> ContentScene:
    return ContentScene(**data)


def _variant(data: dict) -> ContentVariant:
    return ContentVariant(data["variant_id"], data["name"], data["style"], [_scene(item) for item in data["scenes"]])


def _to_domain(model: ContentPlanModel) -> ContentPlan:
    return ContentPlan(model.id, model.project_id, model.script_version_id, model.subtitle_version_id, model.status, model.provider, model.model, [_variant(item) for item in model.variants], model.selected_variant_index, model.total_duration_seconds, model.error_code, model.created_at, model.updated_at, model.confirmed_at)


class ContentPlanRepository:
    def add(self, session: Session, plan: ContentPlan) -> None:
        payload = plan.__dict__.copy()
        payload["variants"] = [{"variant_id": item.variant_id, "name": item.name, "style": item.style, "scenes": [scene.__dict__ for scene in item.scenes]} for item in plan.variants]
        session.add(ContentPlanModel(**payload))

    def get(self, session: Session, plan_id: str) -> ContentPlan | None:
        model = session.get(ContentPlanModel, plan_id)
        return _to_domain(model) if model else None

    def latest(self, session: Session, project_id: str) -> ContentPlan | None:
        model = session.scalar(select(ContentPlanModel).where(ContentPlanModel.project_id == project_id).order_by(ContentPlanModel.created_at.desc()))
        return _to_domain(model) if model else None

    def update(self, session: Session, plan: ContentPlan) -> None:
        model = session.get(ContentPlanModel, plan.id)
        if model is None:
            return
        model.status = plan.status
        model.variants = [{"variant_id": item.variant_id, "name": item.name, "style": item.style, "scenes": [scene.__dict__ for scene in item.scenes]} for item in plan.variants]
        model.selected_variant_index = plan.selected_variant_index
        model.error_code = plan.error_code
        model.updated_at = plan.updated_at
        model.confirmed_at = plan.confirmed_at
