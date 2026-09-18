from __future__ import annotations

from dataclasses import replace

from sqlalchemy.orm import Session

from onetake_api.config import get_settings
from onetake_api.integrations.qwen_creative.adapter import QwenCreativePlanner
from onetake_api.modules.content_plan.domain import STATUS_CONFIRMED, STATUS_READY, ContentPlan, ContentScene, ContentVariant
from onetake_api.modules.content_plan.generator import generate_rule_variants
from onetake_api.modules.content_plan.repository import ContentPlanRepository
from onetake_api.modules.outbox.public import OutboxPublicService
from onetake_api.modules.pipeline.public import PipelinePublicService
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.modules.script.domain import STATUS_CONFIRMED as SCRIPT_CONFIRMED
from onetake_api.modules.script.public import ScriptPublicService
from onetake_api.modules.subtitle.domain import SUBTITLE_CONFIRMED
from onetake_api.modules.subtitle.public import SubtitlePublicService
from onetake_api.platform.clock import SystemClock
from onetake_api.platform.errors import DomainError
from onetake_api.platform.ids import new_id


class ContentPlanNotFoundError(DomainError):
    code = "CONTENT_PLAN_NOT_FOUND"
    http_status = 404


class ContentPlanConflictError(DomainError):
    code = "CONTENT_PLAN_CONFLICT"
    http_status = 409
    retryable = True


class ContentPlanValidationError(DomainError):
    code = "CONTENT_PLAN_VALIDATION_ERROR"
    http_status = 422


class ContentPlanApplicationService:
    def __init__(self) -> None:
        self._repository = ContentPlanRepository()
        self._projects = ProjectPublicService()
        self._scripts = ScriptPublicService()
        self._subtitles = SubtitlePublicService()
        self._pipeline = PipelinePublicService()
        self._outbox = OutboxPublicService()
        self._clock = SystemClock()

    def latest(self, session: Session, project_id: str) -> ContentPlan | None:
        self._projects.get_project(session, project_id=project_id)
        return self._repository.latest(session, project_id)

    def generate(self, session: Session, project_id: str) -> ContentPlan:
        self._projects.get_project(session, project_id=project_id)
        pipeline = self._pipeline.get_or_create(session, project_id)
        if pipeline.status not in {"audio_subtitle_confirmed", "content_plan_ready", "content_plan_confirmed"}:
            raise ContentPlanConflictError("请先确认配音和字幕")
        script_view = self._scripts.latest(session, project_id)
        script = script_view.version
        if script is None or script.status != SCRIPT_CONFIRMED:
            raise ContentPlanConflictError("文案尚未确认")
        subtitle = self._subtitles.latest(session, project_id)
        if subtitle is None or subtitle.status != SUBTITLE_CONFIRMED:
            raise ContentPlanConflictError("字幕尚未确认")
        try:
            variants = generate_rule_variants(segments=subtitle.segments)
        except ValueError as exc:
            raise ContentPlanValidationError(str(exc)) from exc
        settings = get_settings()
        provider = "rules"
        model = "rules-v1"
        if settings.creative_planner_provider == "qwen":
            if not settings.dashscope_api_key:
                raise ContentPlanValidationError("Qwen-Plus 创意缺少 DASHSCOPE_API_KEY")
            planner = QwenCreativePlanner(api_key=settings.dashscope_api_key, endpoint=settings.creative_planner_endpoint, model=settings.creative_planner_model)
            variants = planner.enhance(variants=variants, facts={**script.facts, "hook": script.hook, "pain_point": script.pain_point, "selling_points": script.selling_points, "usage_scenario": script.usage_scenario, "offer": script.offer, "cta": script.cta})
            provider = "qwen-plus"
            model = settings.creative_planner_model
        total_duration = max(18.0, max(float(scene.end_seconds) for variant in variants for scene in variant.scenes))
        now = self._clock.now()
        plan = ContentPlan(
            id=new_id("cpl"), project_id=project_id, script_version_id=script.id, subtitle_version_id=subtitle.id,
            status=STATUS_READY, provider=provider, model=model, variants=variants, selected_variant_index=0,
            total_duration_seconds=total_duration, error_code=None, created_at=now, updated_at=now, confirmed_at=None,
        )
        self._repository.add(session, plan)
        self._pipeline.mark_content_plan_ready(session, project_id)
        self._outbox.enqueue(session, event_name="ContentPlanReady", aggregate_type="content_plan", aggregate_id=plan.id, occurred_at=now, payload={"project_id": project_id, "plan_id": plan.id, "variant_count": len(variants)})
        session.commit()
        return plan

    def update(self, session: Session, project_id: str, *, selected_variant_index: int | None, scenes: list[dict] | None) -> ContentPlan:
        plan = self._require_plan(session, project_id)
        if plan.status == STATUS_CONFIRMED:
            raise ContentPlanConflictError("已确认分镜不能直接修改")
        variants = list(plan.variants)
        index = plan.selected_variant_index if selected_variant_index is None else selected_variant_index
        if index < 0 or index >= len(variants):
            raise ContentPlanValidationError("分镜方案索引无效")
        if scenes is not None:
            if not scenes:
                raise ContentPlanValidationError("分镜不能为空")
            try:
                parsed = [ContentScene(**item) for item in scenes]
            except (TypeError, ValueError) as exc:
                raise ContentPlanValidationError("分镜字段无效") from exc
            variants[index] = replace(variants[index], scenes=parsed)
        updated = replace(plan, variants=variants, selected_variant_index=index, updated_at=self._clock.now())
        self._repository.update(session, updated)
        session.commit()
        return updated

    def confirm(self, session: Session, project_id: str) -> ContentPlan:
        plan = self._require_plan(session, project_id)
        if plan.status == STATUS_CONFIRMED:
            return plan
        now = self._clock.now()
        confirmed = replace(plan, status=STATUS_CONFIRMED, updated_at=now, confirmed_at=now)
        self._repository.update(session, confirmed)
        self._pipeline.mark_content_plan_confirmed(session, project_id)
        self._outbox.enqueue(session, event_name="ContentPlanConfirmed", aggregate_type="content_plan", aggregate_id=plan.id, occurred_at=now, payload={"project_id": project_id, "plan_id": plan.id})
        session.commit()
        return confirmed

    def _require_plan(self, session: Session, project_id: str) -> ContentPlan:
        self._projects.get_project(session, project_id=project_id)
        plan = self._repository.latest(session, project_id)
        if plan is None:
            raise ContentPlanNotFoundError("视频分镜不存在")
        return plan
