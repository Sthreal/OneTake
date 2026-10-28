from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from onetake_api.modules.pipeline.domain import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_INTERRUPTED,
    PipelineRun,
)
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
    # S8/S9+S10：自动链的断点与审计
    stage: Mapped[str | None] = mapped_column(String(40), nullable=True)
    auto_run: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    auto_confirmed_stages: Mapped[list] = mapped_column(JSON, nullable=False, server_default="[]")


def _to_domain(model: PipelineRunModel) -> PipelineRun:
    return PipelineRun(
        id=model.id,
        project_id=model.project_id,
        status=model.status,
        current_step=model.current_step,
        state_version=model.state_version,
        created_at=model.created_at,
        updated_at=model.updated_at,
        stage=model.stage,
        auto_run=model.auto_run,
        auto_confirmed_stages=list(model.auto_confirmed_stages or []),
    )


class PipelineRepository:
    def get(self, session: Session, project_id: str) -> PipelineRun | None:
        model = session.scalar(select(PipelineRunModel).where(PipelineRunModel.project_id == project_id))
        return _to_domain(model) if model else None

    def get_by_id(self, session: Session, run_id: str) -> PipelineRun | None:
        model = session.get(PipelineRunModel, run_id)
        return _to_domain(model) if model else None

    def add(self, session: Session, run: PipelineRun) -> None:
        session.add(PipelineRunModel(
            id=run.id, project_id=run.project_id, status=run.status,
            current_step=run.current_step, state_version=run.state_version,
            created_at=run.created_at, updated_at=run.updated_at,
            stage=run.stage, auto_run=run.auto_run, auto_confirmed_stages=list(run.auto_confirmed_stages),
        ))

    def list_in_flight(self, session: Session) -> list[PipelineRun]:
        """自动链跑过、但还没走到终态的 run（S10 孤儿检测的输入）。

        纯 DB 判断分不出「真在跑」与「进程已死」—— 那一半由推进器的进程内注册表提供，
        这里只负责把候选集合缩小到「自动链 + 非终态」。
        """
        models = session.scalars(
            select(PipelineRunModel).where(
                PipelineRunModel.auto_run.is_(True),
                PipelineRunModel.status.not_in([STATUS_COMPLETED, STATUS_FAILED, STATUS_INTERRUPTED]),
            )
        ).all()
        return [_to_domain(model) for model in models]

    def update(self, session: Session, run: PipelineRun) -> None:
        model = session.get(PipelineRunModel, run.id)
        if model:
            model.status = run.status
            model.current_step = run.current_step
            model.state_version = run.state_version
            model.updated_at = run.updated_at
            model.stage = run.stage
            model.auto_run = run.auto_run
            model.auto_confirmed_stages = list(run.auto_confirmed_stages)
