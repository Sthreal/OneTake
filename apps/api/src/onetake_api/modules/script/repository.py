from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from onetake_api.modules.script.domain import ScriptVersion
from onetake_api.platform.database import Base


class ScriptVersionModel(Base):
    __tablename__ = "versions"
    __table_args__ = (
        UniqueConstraint("project_id", "version_number", name="uq_script_project_version"),
        {"schema": "script"},
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(60), nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    source_object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    facts: Mapped[dict] = mapped_column(JSON, nullable=False)
    hook: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    pain_point: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    selling_points: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    usage_scenario: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    offer: Mapped[str | None] = mapped_column(String(160), nullable=True)
    cta: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    full_text: Mapped[str] = mapped_column(String(1200), nullable=False, default="")
    character_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_duration_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def _to_domain(model: ScriptVersionModel) -> ScriptVersion:
    return ScriptVersion(
        id=model.id,
        project_id=model.project_id,
        version_number=model.version_number,
        status=model.status,
        provider=model.provider,
        model=model.model,
        source_object_key=model.source_object_key,
        facts=model.facts,
        hook=model.hook,
        pain_point=model.pain_point,
        selling_points=list(model.selling_points),
        usage_scenario=model.usage_scenario,
        offer=model.offer,
        cta=model.cta,
        full_text=model.full_text,
        character_count=model.character_count,
        estimated_duration_seconds=model.estimated_duration_seconds,
        error_code=model.error_code,
        created_at=model.created_at,
        updated_at=model.updated_at,
        completed_at=model.completed_at,
        confirmed_at=model.confirmed_at,
    )


class ScriptRepository:
    def add(self, session: Session, version: ScriptVersion) -> None:
        session.add(ScriptVersionModel(**version.__dict__))

    def get(self, session: Session, version_id: str) -> ScriptVersion | None:
        model = session.get(ScriptVersionModel, version_id)
        return _to_domain(model) if model else None

    def latest(self, session: Session, project_id: str) -> ScriptVersion | None:
        model = session.scalar(
            select(ScriptVersionModel)
            .where(ScriptVersionModel.project_id == project_id)
            .order_by(ScriptVersionModel.version_number.desc())
        )
        return _to_domain(model) if model else None

    def next_version_number(self, session: Session, project_id: str) -> int:
        latest = self.latest(session, project_id)
        return (latest.version_number + 1) if latest else 1

    def update(self, session: Session, version: ScriptVersion) -> None:
        model = session.get(ScriptVersionModel, version.id)
        if model is None:
            return
        model.status = version.status
        model.hook = version.hook
        model.pain_point = version.pain_point
        model.selling_points = list(version.selling_points)
        model.usage_scenario = version.usage_scenario
        model.offer = version.offer
        model.cta = version.cta
        model.full_text = version.full_text
        model.character_count = version.character_count
        model.estimated_duration_seconds = version.estimated_duration_seconds
        model.error_code = version.error_code
        model.updated_at = version.updated_at
        model.completed_at = version.completed_at
        model.confirmed_at = version.confirmed_at
