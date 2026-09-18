from __future__ import annotations

from sqlalchemy.orm import Session

from onetake_api.modules.subtitle.domain import SubtitleVersion
from onetake_api.modules.subtitle.service import SubtitleApplicationService, SubtitleStartResult


class SubtitlePublicService:
    def __init__(self) -> None:
        self._service = SubtitleApplicationService()

    def latest(self, session: Session, project_id: str) -> SubtitleVersion | None:
        return self._service.latest(session, project_id)

    def start(self, session: Session, **kwargs) -> SubtitleStartResult:
        return self._service.start(session, **kwargs)

    def update_segments(self, session: Session, **kwargs) -> SubtitleVersion:
        return self._service.update_segments(session, **kwargs)

    def confirm(self, session: Session, project_id: str) -> SubtitleVersion:
        return self._service.confirm(session, project_id)

    def process_job(self, session: Session, job_id: str) -> SubtitleVersion:
        return self._service.process_job(session, job_id)
