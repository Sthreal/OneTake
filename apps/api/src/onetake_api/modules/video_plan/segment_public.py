from sqlalchemy.orm import Session

from onetake_api.modules.video_plan.segment_domain import VideoSegment
from onetake_api.modules.video_plan.segment_service import VideoSegmentApplicationService


class VideoSegmentPublicService:
    def __init__(self) -> None:
        self._service = VideoSegmentApplicationService()

    def materialize_segments(self, session: Session, *, project_id: str, plan_id: str | None = None) -> list[VideoSegment]:
        return self._service.materialize_segments(session, project_id=project_id, plan_id=plan_id)

    def generate_candidate(self, session: Session, *, project_id: str, segment_id: str, seed: int | None = None) -> list[VideoSegment]:
        return self._service.generate_candidate(session, project_id=project_id, segment_id=segment_id, seed=seed)

    def start_batch(self, session: Session, *, project_id: str, job_id: str | None = None):
        return self._service.start_batch(session, project_id=project_id, job_id=job_id)

    def stop_batch(self, session: Session, *, project_id: str):
        return self._service.stop_batch(session, project_id=project_id)

    def continue_batch(self, session: Session, *, project_id: str, job_id: str | None = None):
        return self._service.continue_batch(session, project_id=project_id, job_id=job_id)

    def accept_candidate(self, session: Session, *, project_id: str, candidate_id: str) -> list[VideoSegment]:
        return self._service.accept_candidate(session, project_id=project_id, candidate_id=candidate_id)

    def reject_segment(self, session: Session, *, project_id: str, segment_id: str) -> list[VideoSegment]:
        return self._service.reject_segment(session, project_id=project_id, segment_id=segment_id)
