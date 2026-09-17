from __future__ import annotations

from sqlalchemy.orm import Session

from onetake_api.modules.main_image.domain import MainImageVersion
from onetake_api.modules.main_image.service import MainImageApplicationService, MainImageView


class MainImagePublicService:
    def __init__(self) -> None:
        self._service = MainImageApplicationService()

    def latest(self, session: Session, project_id: str) -> MainImageView | None:
        return self._service.latest(session, project_id)

    def request(self, session: Session, project_id: str) -> MainImageView:
        return self._service.request(session, project_id)

    def confirm(self, session: Session, project_id: str) -> MainImageView:
        return self._service.confirm(session, project_id)

    def process_image_edit_job(self, session: Session, job_id: str) -> MainImageVersion:
        return self._service.process_image_edit_job(session, job_id)

    def process_matting_job(self, session: Session, job_id: str) -> MainImageVersion:
        return self._service.process_matting_job(session, job_id)

    def process_finalize_job(self, session: Session, job_id: str) -> MainImageVersion:
        return self._service.process_finalize_job(session, job_id)
