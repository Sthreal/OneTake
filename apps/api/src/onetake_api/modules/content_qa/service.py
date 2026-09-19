from __future__ import annotations

from onetake_api.modules.content_plan.domain import STATUS_CONFIRMED
from onetake_api.modules.content_plan.repository import ContentPlanRepository
from onetake_api.modules.content_qa.domain import STATUS_FAILED, STATUS_PASSED, ContentQaReport, QaRequest
from onetake_api.modules.content_qa.repository import ContentQaRepository
from onetake_api.config import get_settings
from onetake_api.integrations.qwen_vl_quality.adapter import QwenVlSemanticAdapter
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

    def evaluate_candidate(self, session, *, project_id: str, video_plan_id: str, video_bytes: bytes, metadata: object, expected_audio: bool, subtitle_embedded: bool, product_layered: bool, product_image_bytes: bytes | None = None) -> ContentQaReport:
        plan = self._plans.latest(session, project_id)
        if plan is None or plan.status != STATUS_CONFIRMED:
            raise ContentQaConflictError("请先确认视频分镜")
        request = QaRequest(plan=plan, metadata=metadata, size_bytes=len(video_bytes), expected_audio=expected_audio, subtitle_embedded=subtitle_embedded, product_layered=product_layered, video_bytes=video_bytes, product_image_bytes=product_image_bytes)
        rule_result = self._adapter.evaluate(request)
        semantic_result = None
        settings = get_settings()
        if settings.content_qa_provider == "qwen":
            if not settings.dashscope_api_key:
                raise ContentQaConflictError("Qwen 语义质检缺少 DASHSCOPE_API_KEY")
            semantic_adapter = QwenVlSemanticAdapter(api_key=settings.dashscope_api_key, endpoint=settings.content_qa_endpoint, model=settings.content_qa_model, frame_count=settings.content_qa_frame_count)
            semantic_result = semantic_adapter.evaluate(request)
        score = rule_result.score if semantic_result is None else round(rule_result.score * 0.5 + semantic_result.score * 0.5)
        passed = rule_result.passed if semantic_result is None else rule_result.passed and semantic_result.passed
        checks = rule_result.checks + (semantic_result.checks if semantic_result else [])
        critical = rule_result.critical_failures + (semantic_result.issues if semantic_result else [])
        provider = self._adapter.provider_name if semantic_result is None else f"{self._adapter.provider_name}+{semantic_adapter.provider_name}"
        model = self._adapter.model_name if semantic_result is None else f"{self._adapter.model_name}+{semantic_adapter.model}"
        now = self._clock.now()
        report = ContentQaReport(new_id("qar"), project_id, plan.id, video_plan_id, STATUS_PASSED if passed else STATUS_FAILED, score, passed, checks, critical, provider, model, now, rule_result.score, None if semantic_result is None else semantic_result.score, [] if semantic_result is None else semantic_result.checks, [] if semantic_result is None else semantic_result.issues)
        self._repository.add(session, report)
        if passed:
            self._pipeline.mark_content_qa_passed(session, project_id)
        else:
            self._pipeline.mark_content_qa_failed(session, project_id)
        session.commit()
        return report
