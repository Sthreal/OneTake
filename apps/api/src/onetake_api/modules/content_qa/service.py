from __future__ import annotations

from onetake_api.integrations.mock_video.renderer import VideoMetadata
from onetake_api.modules.content_plan.domain import STATUS_CONFIRMED
from onetake_api.modules.content_plan.repository import ContentPlanRepository
from onetake_api.modules.content_qa.domain import STATUS_FAILED, STATUS_PASSED, ContentQaReport, QaRequest
from onetake_api.modules.content_qa.repository import ContentQaRepository
from onetake_api.modules.content_qa.rules import RuleContentQaAdapter
from onetake_api.modules.pipeline.public import PipelinePublicService
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.platform.clock import SystemClock
from onetake_api.platform.errors import DomainError
from onetake_api.platform.ids import new_id


class ContentQaConflictError(DomainError):
    code = "CONTENT_QA_CONFLICT"
    http_status = 409
    retryable = True


class ContentQaApplicationService:
    def __init__(self, adapter: RuleContentQaAdapter | None = None) -> None:
        self._repository = ContentQaRepository()
        self._plans = ContentPlanRepository()
        self._projects = ProjectPublicService()
        self._pipeline = PipelinePublicService()
        self._adapter = adapter or RuleContentQaAdapter()
        self._clock = SystemClock()

    def latest(self, session, project_id: str) -> ContentQaReport | None:
        self._projects.get_project(session, project_id=project_id)
        return self._repository.latest(session, project_id)

    def evaluate_candidate(self, session, *, project_id: str, video_plan_id: str, video_bytes: bytes, metadata: VideoMetadata, expected_audio: bool, subtitle_embedded: bool, product_layered: bool) -> ContentQaReport:
        plan = self._plans.latest(session, project_id)
        if plan is None or plan.status != STATUS_CONFIRMED:
            raise ContentQaConflictError("请先确认视频分镜")
        result = self._adapter.evaluate(QaRequest(plan=plan, metadata=metadata, size_bytes=len(video_bytes), expected_audio=expected_audio, subtitle_embedded=subtitle_embedded, product_layered=product_layered, video_bytes=video_bytes))
        now = self._clock.now()
        report = ContentQaReport(new_id("qar"), project_id, plan.id, video_plan_id, STATUS_PASSED if result.passed else STATUS_FAILED, result.score, result.passed, result.checks, result.critical_failures, self._adapter.provider_name, self._adapter.model_name, now)
        self._repository.add(session, report)
        if result.passed:
            self._pipeline.mark_content_qa_passed(session, project_id)
        else:
            self._pipeline.mark_content_qa_failed(session, project_id)
        session.commit()
        return report
