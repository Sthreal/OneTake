from __future__ import annotations

from sqlalchemy.orm import Session

from onetake_api.modules.voice.domain import VoiceRun
from onetake_api.modules.voice.service import VoiceApplicationService, VoiceView


class VoicePublicService:
    def __init__(self) -> None:
        self._service = VoiceApplicationService()

    def latest(self, session: Session, project_id: str) -> VoiceView:
        return self._service.latest(session, project_id)

    def get_run(self, session: Session, run_id: str):
        return self._service.get_run(session, run_id)

    def request(self, session: Session, **kwargs) -> VoiceView:
        return self._service.request(session, **kwargs)

    def confirm(self, session: Session, project_id: str) -> VoiceRun:
        return self._service.confirm(session, project_id)

    def process_job(self, session: Session, job_id: str) -> VoiceRun:
        return self._service.process_job(session, job_id)
