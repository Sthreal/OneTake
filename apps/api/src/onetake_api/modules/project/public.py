from __future__ import annotations

from sqlalchemy.orm import Session

from onetake_api.modules.project.application.commands import CreateProjectCommand
from onetake_api.modules.project.application.queries import GetProjectQuery, ListProjectsQuery
from onetake_api.modules.project.application.service import ProjectApplicationService
from onetake_api.modules.project.domain.model import Project


class ProjectPublicService:
    def __init__(self, ttl_hours: int = 24) -> None:
        self._service = ProjectApplicationService(ttl_hours=ttl_hours)

    def create_project(
        self,
        session: Session,
        *,
        product_name: str,
        product_note: str | None,
    ) -> Project:
        return self._service.create_project(
            session,
            CreateProjectCommand(product_name=product_name, product_note=product_note),
        )

    def get_project(self, session: Session, *, project_id: str) -> Project:
        return self._service.get_project(session, GetProjectQuery(project_id=project_id))

    def list_projects(self, session: Session, *, limit: int = 20) -> list[Project]:
        return self._service.list_projects(session, ListProjectsQuery(limit=limit))