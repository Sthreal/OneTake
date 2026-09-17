from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from onetake_api.modules.outbox.public import OutboxPublicService
from onetake_api.modules.project.adapters.sqlalchemy_repository import SqlAlchemyProjectRepository
from onetake_api.modules.project.application.commands import CreateProjectCommand
from onetake_api.modules.project.application.queries import GetProjectQuery
from onetake_api.modules.project.domain.errors import ProjectNotFoundError
from onetake_api.modules.project.domain.model import Project, create_project_entity
from onetake_api.platform.clock import SystemClock
from onetake_api.platform.ids import new_id


class ProjectApplicationService:
    def __init__(self, ttl_hours: int = 24) -> None:
        self._repository = SqlAlchemyProjectRepository()
        self._clock = SystemClock()
        self._ttl_hours = ttl_hours

    def create_project(self, session: Session, command: CreateProjectCommand) -> Project:
        now = self._clock.now()
        project = create_project_entity(
            project_id=new_id("prj"),
            product_name=command.product_name,
            product_note=command.product_note,
            now=now,
            expires_at=now + timedelta(hours=self._ttl_hours),
        )
        self._repository.add(session, project)
        OutboxPublicService().enqueue(
            session,
            event_name="ProjectCreated",
            aggregate_type="project",
            aggregate_id=project.id,
            occurred_at=now,
            payload={
                "project_id": project.id,
                "product_name": project.product_name,
                "created_at": project.created_at.isoformat(),
            },
        )
        session.flush()
        return project

    def get_project(self, session: Session, query: GetProjectQuery) -> Project:
        project = self._repository.get(session, query.project_id)
        if project is None:
            raise ProjectNotFoundError("项目不存在")
        return project