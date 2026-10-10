from sqlalchemy.orm import Session

from onetake_api.modules.video_plan.segment_domain import VideoSegment
from onetake_api.modules.video_plan.segment_service import VideoSegmentApplicationService


class VideoSegmentPublicService:
    def __init__(self) -> None:
        self._service = VideoSegmentApplicationService()

    def materialize_segments(self, session: Session, *, project_id: str, plan_id: str | None = None) -> list[VideoSegment]:
        return self._service.materialize_segments(session, project_id=project_id, plan_id=plan_id)

    def accept_candidate(self, session: Session, *, project_id: str, candidate_id: str) -> list[VideoSegment]:
        return self._service.accept_candidate(session, project_id=project_id, candidate_id=candidate_id)

    def reject_segment(self, session: Session, *, project_id: str, segment_id: str) -> list[VideoSegment]:
        return self._service.reject_segment(session, project_id=project_id, segment_id=segment_id)
