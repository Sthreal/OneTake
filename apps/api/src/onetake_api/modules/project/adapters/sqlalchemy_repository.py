from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from onetake_api.modules.project.domain.model import Project
from onetake_api.platform.database import Base


class ProjectModel(Base):
    __tablename__ = "projects"
    __table_args__ = {"schema": "project"}

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    product_name: Mapped[str] = mapped_column(String(80), nullable=False)
    product_note: Mapped[str | None] = mapped_column(String(240), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _to_domain(model: ProjectModel) -> Project:
    return Project(
        id=model.id,
        product_name=model.product_name,
        product_note=model.product_note,
        status=model.status,
        created_at=model.created_at,
        updated_at=model.updated_at,
        expires_at=model.expires_at,
    )


class SqlAlchemyProjectRepository:
    def add(self, session: Session, project: Project) -> None:
        session.add(
            ProjectModel(
                id=project.id,
                product_name=project.product_name,
                product_note=project.product_note,
                status=project.status,
                created_at=project.created_at,
                updated_at=project.updated_at,
                expires_at=project.expires_at,
            )
        )

    def get(self, session: Session, project_id: str) -> Project | None:
        model = session.get(ProjectModel, project_id)
        return _to_domain(model) if model else None

    def list_projects(self, session: Session, limit: int) -> list[Project]:
        models = session.scalars(
            select(ProjectModel).order_by(ProjectModel.created_at.desc()).limit(limit)
        ).all()
        return [_to_domain(model) for model in models]