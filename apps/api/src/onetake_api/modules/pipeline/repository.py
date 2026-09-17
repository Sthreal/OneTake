from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from onetake_api.modules.pipeline.domain import PipelineRun
from onetake_api.platform.database import Base


class PipelineRunModel(Base):
    __tablename__ = "pipeline_runs"
    __table_args__ = {"schema": "pipeline"}

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    current_step: Mapped[int] = mapped_column(Integer, nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _to_domain(model: PipelineRunModel) -> PipelineRun:
    return PipelineRun(
        id=model.id,
        project_id=model.project_id,
        status=model.status,
        current_step=model.current_step,
        state_version=model.state_version,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class PipelineRepository:
    def get(self, session: Session, project_id: str) -> PipelineRun | None:
        model = session.scalar(select(PipelineRunModel).where(PipelineRunModel.project_id == project_id))
        return _to_domain(model) if model else None

    def add(self, session: Session, run: PipelineRun) -> None:
        session.add(PipelineRunModel(
            id=run.id, project_id=run.project_id, status=run.status,
            current_step=run.current_step, state_version=run.state_version,
            created_at=run.created_at, updated_at=run.updated_at,
        ))

    def update(self, session: Session, run: PipelineRun) -> None:
        model = session.get(PipelineRunModel, run.id)
        if model:
            model.status = run.status
            model.current_step = run.current_step
            model.state_version = run.state_version
            model.updated_at = run.updated_at
