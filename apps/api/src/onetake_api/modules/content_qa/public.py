from onetake_api.modules.content_qa.service import ContentQaApplicationService


class ContentQaPublicService:
    def __init__(self) -> None:
        self._service = ContentQaApplicationService()

    def latest(self, session, project_id: str):
        return self._service.latest(session, project_id)

    def evaluate_candidate(self, session, **kwargs):
        return self._service.evaluate_candidate(session, **kwargs)
