from onetake_api.modules.video_plan.keyframe_domain import VideoKeyframeCandidate
from onetake_api.modules.video_plan.keyframe_service import VideoKeyframeApplicationService


class VideoKeyframePublicService:
    def __init__(self) -> None:
        self._service = VideoKeyframeApplicationService()

    def list_candidates(self, session, *, project_id: str) -> list[VideoKeyframeCandidate]:
        return self._service.list_candidates(session, project_id=project_id)

    def generate_candidate(self, session, **kwargs) -> list[VideoKeyframeCandidate]:
        return self._service.generate_candidate(session, **kwargs)

    def accept_candidate(self, session, **kwargs) -> list[VideoKeyframeCandidate]:
        return self._service.accept_candidate(session, **kwargs)