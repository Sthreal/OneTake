from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from onetake_api.modules.content_qa.domain import ContentQaReport, QaCheck
from onetake_api.platform.database import Base


class ContentQaReportModel(Base):
    __tablename__ = "reports"
    __table_args__ = {"schema": "content_qa"}

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    plan_id: Mapped[str] = mapped_column(String(40), nullable=False)
    video_plan_id: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    checks: Mapped[list] = mapped_column(JSON, nullable=False)
    critical_failures: Mapped[list] = mapped_column(JSON, nullable=False)
    provider: Mapped[str] = mapped_column(String(60), nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rule_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    semantic_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    semantic_checks: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    semantic_issues: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


def _to_domain(model: ContentQaReportModel) -> ContentQaReport:
    return ContentQaReport(model.id, model.project_id, model.plan_id, model.video_plan_id, model.status, model.score, model.passed, [QaCheck(**item) for item in model.checks], list(model.critical_failures), model.provider, model.model, model.created_at, model.rule_score, model.semantic_score, [QaCheck(**item) for item in model.semantic_checks], list(model.semantic_issues))


class ContentQaRepository:
    def add(self, session: Session, report: ContentQaReport) -> None:
        payload = report.__dict__.copy()
        payload["checks"] = [item.__dict__ for item in report.checks]
        payload["semantic_checks"] = [item.__dict__ for item in report.semantic_checks]
        session.add(ContentQaReportModel(**payload))

    def latest(self, session: Session, project_id: str) -> ContentQaReport | None:
        model = session.scalar(select(ContentQaReportModel).where(ContentQaReportModel.project_id == project_id).order_by(ContentQaReportModel.created_at.desc()))
        return _to_domain(model) if model else None
