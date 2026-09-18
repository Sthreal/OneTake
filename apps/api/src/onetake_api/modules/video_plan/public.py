from sqlalchemy.orm import Session

from onetake_api.modules.video_plan.domain import VideoPlan
from onetake_api.modules.video_plan.service import VideoPlanApplicationService, VideoView


class VideoPlanPublicService:
    def __init__(self) -> None:
        self._service = VideoPlanApplicationService()

    def latest(self, session: Session, project_id: str) -> VideoView:
        return self._service.latest(session, project_id)

    def create_plan(self, session: Session, **kwargs) -> VideoView:
        return self._service.create_plan(session, **kwargs)

    def request_video(self, session: Session, project_id: str) -> VideoView:
        return self._service.request_video(session, project_id)

    def process_job(self, session: Session, job_id: str) -> VideoPlan:
        return self._service.process_job(session, job_id)
