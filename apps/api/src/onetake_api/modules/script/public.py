from __future__ import annotations

from sqlalchemy.orm import Session

from onetake_api.modules.script.service import ScriptApplicationService, ScriptView


class ScriptPublicService:
    def __init__(self) -> None:
        self._service = ScriptApplicationService()

    def latest(self, session: Session, project_id: str) -> ScriptView:
        return self._service.latest(session, project_id)

    def request(self, session: Session, **kwargs) -> ScriptView:
        return self._service.request(session, **kwargs)

    def update(self, session: Session, **kwargs) -> ScriptView:
        return self._service.update(session, **kwargs)

    def confirm(self, session: Session, project_id: str) -> ScriptView:
        return self._service.confirm(session, project_id)

    def process_job(self, session: Session, job_id: str):
        return self._service.process_job(session, job_id)
