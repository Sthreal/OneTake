from sqlalchemy.orm import Session

from onetake_api.modules.recognition.domain import RecognitionCandidate, RecognitionRun
from onetake_api.modules.recognition.service import RecognitionService


class RecognitionPublicService:
    def request(self, session: Session, project_id: str) -> RecognitionRun:
        return RecognitionService().request(session, project_id)

    def latest(self, session: Session, project_id: str) -> tuple[RecognitionRun | None, list[RecognitionCandidate]]:
        return RecognitionService().latest(session, project_id)

    def confirm(self, session: Session, project_id: str, run_id: str, candidate_id: str) -> RecognitionRun:
        return RecognitionService().confirm(session, project_id, run_id, candidate_id)
