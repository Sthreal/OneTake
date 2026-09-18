from sqlalchemy.orm import Session

from onetake_api.modules.content_plan.service import ContentPlanApplicationService


class ContentPlanPublicService:
    def __init__(self) -> None:
        self._service = ContentPlanApplicationService()

    def latest(self, session: Session, project_id: str):
        return self._service.latest(session, project_id)

    def generate(self, session: Session, project_id: str):
        return self._service.generate(session, project_id)

    def update(self, session: Session, **kwargs):
        return self._service.update(session, **kwargs)

    def confirm(self, session: Session, project_id: str):
        return self._service.confirm(session, project_id)
