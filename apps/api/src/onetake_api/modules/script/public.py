from __future__ import annotations

from sqlalchemy.orm import Session

from onetake_api.modules.script.service import ScriptApplicationService, ScriptReviewView, ScriptView


class ScriptPublicService:
    def __init__(self) -> None:
        self._service = ScriptApplicationService()

    def latest(self, session: Session, project_id: str) -> ScriptView:
        return self._service.latest(session, project_id)

    def request(self, session: Session, **kwargs) -> ScriptView:
        return self._service.request(session, **kwargs)

    def update(self, session: Session, **kwargs) -> ScriptView:
        return self._service.update(session, **kwargs)

    def select(self, session: Session, **kwargs) -> ScriptView:
        return self._service.select(session, **kwargs)

    def confirm(self, session: Session, project_id: str, *, enforce_review_gate: bool = True) -> ScriptView:
        return self._service.confirm(session, project_id, enforce_review_gate=enforce_review_gate)

    def review(self, session: Session, project_id: str) -> ScriptReviewView:
        return self._service.review(session, project_id)

    def apply_review(self, session: Session, project_id: str, *, action: str) -> ScriptReviewView:
        return self._service.apply_review(session, project_id, action=action)

    def review_gate_passed(self, session: Session, project_id: str) -> bool:
        return self._service.review_gate_passed(session, project_id)

    def process_job(self, session: Session, job_id: str):
        return self._service.process_job(session, job_id)
