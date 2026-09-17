from __future__ import annotations

from sqlalchemy.orm import Session

from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.modules.matting.domain import MattingRun
from onetake_api.modules.matting.service import MattingApplicationService, MattingStartResult


class MattingPublicService:
    def __init__(self) -> None:
        self._service = MattingApplicationService()

    def start(self, session: Session, **kwargs) -> MattingStartResult:
        return self._service.start(session, **kwargs)

    def get(self, session: Session, run_id: str) -> MattingRun | None:
        return self._service.get(session, run_id)

    def latest_for_version(self, session: Session, version_id: str) -> MattingRun | None:
        return self._service.latest_for_version(session, version_id)

    def process_job(
        self,
        session: Session,
        *,
        job_id: str,
        storage: ObjectStoragePublicService,
    ) -> MattingRun:
        return self._service.process_job(session, job_id=job_id, storage=storage)
