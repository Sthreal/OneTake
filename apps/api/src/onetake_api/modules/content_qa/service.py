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


class SegmentQualityMediaMissingError(DomainError):
    """素材已被清理 / 不存在 —— 明确报 409，而不是让它变成一个 500。"""

    code = "SEGMENT_QUALITY_MEDIA_MISSING"
    http_status = 409
    retryable = False


class SegmentQualityDisabledError(DomainError):
    code = "SEGMENT_QUALITY_DISABLED"
    http_status = 409
    retryable = False


def _build_segment_quality_adapter(settings):
    """按配置造适配器：目前只有 Qwen-VL；缺 Key **显式报错**（不静默降级成"评分通过"）。"""
    from onetake_api.integrations.qwen_vl_quality.adapter import QwenVlSemanticAdapter

    if not settings.dashscope_api_key:
        raise ContentQaConflictError("逐镜评分缺少 DASHSCOPE_API_KEY")
    return QwenVlSemanticAdapter(
        api_key=settings.dashscope_api_key, endpoint=settings.content_qa_endpoint,
        model=settings.content_qa_model, frame_count=settings.content_qa_frame_count,
    )


class ContentQaConflictError(DomainError):
    code = "CONTENT_QA_CONFLICT"
    http_status = 409
    retryable = True


class ContentQaApplicationService:
    def __init__(self, adapter: RuleContentQaAdapter | None = None, *, storage=None) -> None:
        self._repository = ContentQaRepository()
        self._plans = ContentPlanRepository()
        self._projects = ProjectPublicService()
        self._pipeline = PipelinePublicService()
        self._adapter = adapter or RuleContentQaAdapter()
        self._clock = SystemClock()
        self._storage = storage

    @property
    def storage(self):
        if self._storage is None:
            from onetake_api.integrations.object_storage.dependencies import get_object_storage
            self._storage = get_object_storage()
        return self._storage

    # ---- 批次 5：逐镜 VLM 评分 ----

    def _read_media(self, object_key: str | None, *, what: str) -> bytes:
        """读素材；**读不到就明确报 409**（旧项目的素材会被媒体清理任务删掉，那不该变成 500）。"""
        if not object_key:
            raise SegmentQualityMediaMissingError(f"{what}缺失（对象键为空）：请换一个项目或重新生成")
        try:
            content = b"".join(self.storage.read_object(object_key=object_key))
        except Exception as exc:  # noqa: BLE001 - 存储层的各种异常统一翻译成"素材不可用"
            raise SegmentQualityMediaMissingError(f"{what}已不存在或不可读：{object_key}") from exc
        if not content:
            raise SegmentQualityMediaMissingError(f"{what}为空：{object_key}")
        return content

    def score_segments(self, session, *, project_id: str, adapter=None):
        """对**已采用**的分段逐镜打分，写侧车报告并返回。

        - 默认关闭（`SEGMENT_QUALITY_ENABLED`）；关闭时**显式报错**而不是假装跑过；
        - 只评"已采用"的分段（没采用的候选评价没有意义）；
        - 模型适配器可注入（测试用假适配器，不联网、不花钱）。
        """
        # 局部 import：`video_plan.public` 会反向 import 本模块，放模块级会成环（实测踩到）
        from onetake_api.modules.content_qa import segment_quality
        from onetake_api.modules.video_plan.public import VideoPlanPublicService
        from onetake_api.modules.video_plan.segment_repository import VideoSegmentRepository

        settings = get_settings()
        if adapter is None and not settings.segment_quality_enabled:
            raise SegmentQualityDisabledError("逐镜评分未启用（SEGMENT_QUALITY_ENABLED=false）")
        view = self._projects.get_project(session, project_id=project_id)
        plan_view = VideoPlanPublicService().latest(session, project_id)
        plan = getattr(plan_view, "plan", None)
        if plan is None:
            # 注意：**不要求已成片** —— 分段采用后就能评（这正是逐镜评分的价值所在：
            # 在花合成钱之前先知道哪一镜不行）
            raise ContentQaConflictError("还没有视频方案，无法逐镜评分")
        content_plan = self._plans.latest(session, project_id)
        scenes = {}
        if content_plan is not None:
            variant = content_plan.variants[content_plan.selected_variant_index]
            scenes = {scene.scene_id: scene for scene in variant.scenes}
        segments = [
            segment for segment in VideoSegmentRepository().list_for_plan(session, plan.id)
            if segment.accepted_candidate_id
        ]
        if not segments:
            raise ContentQaConflictError("还没有已采用的分段，无法逐镜评分")

        engine = adapter or _build_segment_quality_adapter(settings)
        product_image = self._read_media(plan.main_image_object_key, what="主图")
        results: list[tuple[str, int, str, dict[str, int], list[str], list[float]]] = []
        calls = 0
        # 真实用量（tokens）：汇总进报告 → 用来校准"每次调用多少钱"
        usage_total: dict[str, int] = {}
        for segment in segments:
            candidate = next(
                (item for item in segment.candidates if item.id == segment.accepted_candidate_id), None
            )
            if candidate is None or not candidate.video_object_key:
                continue
            scene = scenes.get(segment.scene_id)
            video_bytes = self._read_media(candidate.video_object_key, what=f"第 {segment.order_index} 段视频")
            outcome = engine.score_segment(
                video_bytes=video_bytes,
                duration_seconds=float(candidate.duration_seconds or segment.duration_seconds),
                product_image_bytes=product_image,
                script_excerpt=getattr(scene, "script_excerpt", "") or "",
                shot_prompt=getattr(scene, "prompt", "") or "",
                # `segment.order_index` 直接来自内容方案的 `scene.order`（生产里是 1 基），
                # 所以这里**不再 +1**：加两次会让提示词与实际镜号错位（真机上踩到过）
                order_index=segment.order_index,
                total_segments=len(segments),
            )
            calls += 1
            for key, value in dict(getattr(outcome, "usage", None) or {}).items():
                if isinstance(value, int):
                    usage_total[key] = usage_total.get(key, 0) + value
            results.append((
                # 报告里的镜号沿用 segment.order_index（= scene.order，生产为 1 基），与提示词一致
                segment.id, segment.order_index, segment.scene_id,
                dict(outcome.scores), list(outcome.issues), list(outcome.evidence_seconds),
            ))
        report = segment_quality.build_report(
            project_id=project_id, plan_id=plan.id,
            provider=getattr(engine, "provider_name", "unknown"),
            model=getattr(engine, "model", "unknown"),
            calls=calls, segments=results, usage=usage_total,
        )
        segment_quality.write_report(self.storage, report)
        return report

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
        report = ContentQaReport(new_id("qar"), project_id, plan.id, video_plan_id, STATUS_PASSED if passed else STATUS_FAILED, score, passed, checks, critical, provider, model, now, rule_result.score, None if semantic_result is None else semantic_result.score, [] if semantic_result is None else semantic_result.checks, [] if semantic_result is None else semantic_result.issues, rule_result.signals)
        self._repository.add(session, report)
        if passed:
            self._pipeline.mark_content_qa_passed(session, project_id)
        else:
            self._pipeline.mark_content_qa_failed(session, project_id)
        session.commit()
        return report
