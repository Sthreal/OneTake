from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from onetake_api.modules.recognition.domain import RecognitionCandidate, RecognitionRun
from onetake_api.platform.database import Base


class RecognitionRunModel(Base):
    __tablename__ = "runs"
    __table_args__ = {"schema": "recognition"}
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    selected_asset_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    selected_candidate_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CandidateModel(Base):
    __tablename__ = "candidates"
    __table_args__ = {"schema": "recognition"}
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    asset_id: Mapped[str] = mapped_column(String(40), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(String(240), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _run(model: RecognitionRunModel) -> RecognitionRun:
    return RecognitionRun(model.id, model.project_id, model.status, model.input_hash, model.selected_asset_id, model.selected_candidate_id, model.error_code, model.created_at, model.updated_at, model.completed_at)


def _candidate(model: CandidateModel) -> RecognitionCandidate:
    return RecognitionCandidate(model.id, model.run_id, model.asset_id, model.label, model.confidence, model.reason, model.created_at)


class RecognitionRepository:
    def add_run(self, session: Session, run: RecognitionRun) -> None:
        session.add(RecognitionRunModel(**run.__dict__))

    def update_run(self, session: Session, run: RecognitionRun) -> None:
        model = session.get(RecognitionRunModel, run.id)
        if model:
            model.status = run.status
            model.selected_asset_id = run.selected_asset_id
            model.selected_candidate_id = run.selected_candidate_id
            model.error_code = run.error_code
            model.updated_at = run.updated_at
            model.completed_at = run.completed_at

    def get_run(self, session: Session, run_id: str) -> RecognitionRun | None:
        model = session.get(RecognitionRunModel, run_id)
        return _run(model) if model else None

    def latest_run(self, session: Session, project_id: str) -> RecognitionRun | None:
        model = session.scalar(select(RecognitionRunModel).where(RecognitionRunModel.project_id == project_id).order_by(RecognitionRunModel.created_at.desc()))
        return _run(model) if model else None

    def add_candidates(self, session: Session, candidates: list[RecognitionCandidate]) -> None:
        session.add_all([CandidateModel(**candidate.__dict__) for candidate in candidates])

    def list_candidates(self, session: Session, run_id: str) -> list[RecognitionCandidate]:
        models = session.scalars(select(CandidateModel).where(CandidateModel.run_id == run_id).order_by(CandidateModel.confidence.desc())).all()
        return [_candidate(model) for model in models]

    def get_candidate(self, session: Session, candidate_id: str) -> RecognitionCandidate | None:
        model = session.get(CandidateModel, candidate_id)
        return _candidate(model) if model else None
