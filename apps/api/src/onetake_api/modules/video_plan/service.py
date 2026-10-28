from __future__ import annotations

import logging

import hashlib
import math
from dataclasses import asdict
from io import BytesIO
from pathlib import Path
import wave
from dataclasses import dataclass, replace
from datetime import timedelta

from sqlalchemy.orm import Session

from onetake_api.config import Settings, get_settings
from onetake_api.integrations.media.caption_styles import CaptionStyleError, resolve_caption_style

from onetake_api.integrations.dashscope_uploader.adapter import DashScopeTemporaryUploader
from onetake_api.modules.content_qa.contact_sheet import build_contact_sheet, splice_timestamps
from onetake_api.integrations.media.video_utils import concatenate_videos
from onetake_api.integrations.mock_video.renderer import render_base_video, validate_final_video
from onetake_api.integrations.wan_i2v.adapter import resolution_output_size
from onetake_api.integrations.object_storage.dependencies import get_object_storage
from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.modules.composition.port import CompositionPort, CompositionRequest
from onetake_api.modules.composition.service import get_composition_provider
from onetake_api.modules.content_plan.domain import STATUS_CONFIRMED as CONTENT_PLAN_CONFIRMED
from onetake_api.modules.character.public import CharacterPublicService
from onetake_api.modules.content_plan.public import ContentPlanPublicService
from onetake_api.modules.content_qa.public import ContentQaPublicService

logger = logging.getLogger(__name__)
from onetake_api.modules.job.public import JobPublicService
from onetake_api.modules.main_image.public import MainImagePublicService
from onetake_api.modules.output.domain import OutputArtifact
from onetake_api.modules.output.repository import OutputRepository
from onetake_api.modules.outbox.public import OutboxPublicService
from onetake_api.modules.pipeline.public import PipelinePublicService, cost_payload_hash
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.modules.subtitle.domain import SUBTITLE_CONFIRMED
from onetake_api.modules.subtitle.public import SubtitlePublicService
from onetake_api.modules.video_plan.domain import COMPLETED, FAILED, MOTION_REALISM_AUTO, MOTION_REALISM_TIERS, SEAM_MODES, SEAM_PIN, SEAM_TAIL, GENERATION_PATHS, MODES, PATH_ONE_SHOT, PATH_SEGMENTED, PLAN_READY, PRODUCT_SCENE_TEMPLATES, RENDERING, VIDEO_GENERATING, VIDEO_READY, VideoPlan
from onetake_api.modules.video_plan.estimate import VideoGenerationEstimate, estimate_video_generation
from onetake_api.modules.video_plan.gate import build_gate_report
from onetake_api.modules.video_plan.gate_ack_repository import GateAckRepository
from onetake_api.modules.video_plan.keyframe_domain import KEYFRAME_ACCEPTED
from onetake_api.modules.video_plan.keyframe_repository import VideoKeyframeCandidateRepository
from onetake_api.modules.video_plan.one_shot import keyframe_refs_for_call, plan_one_shot_calls
from onetake_api.modules.video_plan.repository import VideoPlanRepository
from onetake_api.modules.voice.domain import VOICE_CONFIRMED
from onetake_api.modules.voice.public import VoicePublicService
from onetake_api.platform.clock import SystemClock
from onetake_api.platform.errors import DomainError
from onetake_api.platform.ids import new_id
from onetake_api.platform.queue import get_queue

ACTIVE_PIPELINE_STATUSES = {"video_generating", "video_ready", "rendering"}
REGENERABLE_PIPELINE_STATUSES = {"audio_subtitle_confirmed", "content_plan_confirmed", "content_qa_passed", "video_plan_ready", "completed", "failed"}
OUTPUT_URL_SECONDS = 24 * 60 * 60


# 「本次请求没提这个字段」的占位符。
# 为什么需要它：可空旋钮（字幕样式 / BGM）必须能区分两件事 ——
#   **没提** = 不动；**显式 null** = 清除覆盖、回跟随全局配置。
# 只用 `None` 当默认值会把这两件事混成一个（实测踩过：UI 选「跟全局」静默失效）。
KEEP = object()


class VideoPlanNotFoundError(DomainError):
    code = "VIDEO_NOT_FOUND"
    http_status = 404


class VideoPlanConflictError(DomainError):
    code = "VIDEO_CONFLICT"
    http_status = 409
    retryable = True


class VideoPlanValidationError(DomainError):
    code = "VIDEO_VALIDATION_ERROR"
    http_status = 422


@dataclass(frozen=True)
class CostApprovalContext:
    """一次付费动作的「费用上下文」：审批按它来查、按它来记。"""

    plan_id: str
    is_paid: bool
    estimated_cny: float
    payload_hash: str


@dataclass(frozen=True)
class VideoView:
    plan: VideoPlan | None
    video_url: str | None


class VideoPlanApplicationService:
    def __init__(
        self,
        storage: ObjectStoragePublicService | None = None,
        composition: CompositionPort | None = None,
        content_qa: object | None = None,
    ) -> None:
        self._repository = VideoPlanRepository()
        self._outputs = OutputRepository()
        self._projects = ProjectPublicService()
        self._main_images = MainImagePublicService()
        self._voices = VoicePublicService()
        self._subtitles = SubtitlePublicService()
        self._jobs = JobPublicService()
        self._pipeline = PipelinePublicService()
        self._outbox = OutboxPublicService()
        self._clock = SystemClock()
        self._storage = storage
        self._composition = composition or get_composition_provider()
        self._content_qa = content_qa or ContentQaPublicService()
        self._keyframes = VideoKeyframeCandidateRepository()

    @property
    def storage(self) -> ObjectStoragePublicService:
        return self._storage or get_object_storage()

    def latest(self, session: Session, project_id: str) -> VideoView:
        self._projects.get_project(session, project_id=project_id)
        return self._view(self._repository.latest(session, project_id))

    def estimate(self, session: Session, *, project_id: str, plan_id: str) -> VideoGenerationEstimate:
        self._projects.get_project(session, project_id=project_id)
        plan = self._repository.get(session, plan_id)
        if plan is None or plan.project_id != project_id:
            raise VideoPlanNotFoundError("视频方案不存在")
        return estimate_video_generation(
            plan, get_settings(), effective_seams=self._effective_seams(session, plan.id)
        )

    def _effective_seams(self, session: Session, plan_id: str) -> list[str | None]:
        """段级接缝覆盖（按分段顺序）—— 预估与审批哈希都按同一份口径算。"""
        from onetake_api.modules.video_plan.segment_repository import VideoSegmentRepository

        return VideoSegmentRepository().effective_seams(session, plan_id)

    # ---- S8：费用审批（付费动作的唯一闸口；人工 / 自动 / MCP 共用）----

    def cost_approval_context(self, session: Session, *, project_id: str,
                              plan_id: str | None = None) -> CostApprovalContext:
        """算出「这份方案 + 当前配置下的预估」的指纹。

        `payload_hash` 覆盖 plan 身份与**整份预估**（`asdict`）—— 任何影响金额的参数变化都会
        改变它，于是旧审批自动失效（防「用 5 元的预估批了 50 元的方案」）。
        """
        self._projects.get_project(session, project_id=project_id)
        plan = self._repository.get(session, plan_id) if plan_id else self._repository.latest(session, project_id)
        if plan is None or plan.project_id != project_id:
            raise VideoPlanNotFoundError("视频方案不存在")
        estimate = estimate_video_generation(
            plan, get_settings(), effective_seams=self._effective_seams(session, plan.id)
        )
        payload = {
            "plan_id": plan.id,
            "mode": plan.mode,
            "template_id": plan.template_id,
            "path": getattr(plan, "path", PATH_SEGMENTED),
            "duration_seconds": plan.duration_seconds,
            "estimate": asdict(estimate),
        }
        return CostApprovalContext(
            plan_id=plan.id,
            is_paid=estimate.is_paid,
            estimated_cny=estimate.estimated_known_cost,
            payload_hash=cost_payload_hash(payload),
        )

    def require_cost_approval(self, session: Session, *, project_id: str,
                              plan_id: str | None = None) -> CostApprovalContext | None:
        """付费动作的准入检查。两道「不设闸」的口径：

        1. **免费 / mock 的预估**（`is_paid=False`）→ 不设闸，否则 mock 全链路会被误伤；
        2. **还没有视频方案可绑定**（关键帧候选可在建方案之前生成）→ 不设闸，保持既有行为。
           这是本切片**如实登记的缺口**：该子路径（尚无方案时的真实关键帧生成）的费用审批
           未纳入本次闸门，建议后续切片补「项目级审批」或把建方案前置。
        """
        self._projects.get_project(session, project_id=project_id)
        plan = self._repository.get(session, plan_id) if plan_id else self._repository.latest(session, project_id)
        if plan is None or plan.project_id != project_id:
            return None
        context = self.cost_approval_context(session, project_id=project_id, plan_id=plan.id)
        if context.is_paid:
            self._pipeline.require_cost_approval(
                session,
                project_id=project_id,
                plan_id=context.plan_id,
                estimated_cny=context.estimated_cny,
                payload_hash=context.payload_hash,
            )
        return context

    def approve_cost(self, session: Session, *, project_id: str, plan_id: str | None,
                     approved_by: str) -> CostApprovalContext:
        """登记人力批准（幂等：同一份预估重复批准不重复落行）。"""
        context = self.cost_approval_context(session, project_id=project_id, plan_id=plan_id)
        self._pipeline.approve_cost(
            session,
            project_id=project_id,
            plan_id=context.plan_id,
            estimated_cny=context.estimated_cny,
            payload_hash=context.payload_hash,
            approved_by=approved_by,
        )
        return context

    @staticmethod
    def _storyboard_seconds(session: Session, project_id: str) -> float | None:
        """分镜总时长（成片时长的唯一真源）。读不到就返回 None，由调用方回退到配音时长。"""
        plan = ContentPlanPublicService().latest(session, project_id)
        if plan is None or not plan.variants:
            return None
        variant = plan.variants[plan.selected_variant_index]
        ends = [scene.end_seconds for scene in variant.scenes]
        return round(min(25.0, max(8.0, max(ends))), 3) if ends else None

    def create_plan(self, session: Session, *, project_id: str, mode: str, template_id: str | None, path: str | None = None) -> VideoView:
        self._projects.get_project(session, project_id=project_id)
        if mode not in MODES:
            raise VideoPlanValidationError("视频类型必须是有人或无人模式")
        # 生成路径：未指定时取服务端默认（MCP 等旧调用方只发 mode/template_id，必须能继续工作）
        resolved_path = path or get_settings().generation_path_default
        if resolved_path not in GENERATION_PATHS:
            raise VideoPlanValidationError("生成路径必须是 segmented 或 one_shot")
        # 档位只剩 product（M4-04），模板校验直接生效，无需再按 mode 分支
        if template_id not in PRODUCT_SCENE_TEMPLATES:
            raise VideoPlanValidationError("无人模式必须选择有效模板")
        pipeline = self._pipeline.get_or_create(session, project_id)
        if pipeline.status in ACTIVE_PIPELINE_STATUSES:
            raise VideoPlanConflictError("视频正在生成，请等待完成")
        if pipeline.status not in REGENERABLE_PIPELINE_STATUSES:
            raise VideoPlanConflictError("请先确认配音和字幕")
        voice_view = self._voices.latest(session, project_id)
        subtitle = self._subtitles.latest(session, project_id)
        if voice_view.run is None or voice_view.run.status != VOICE_CONFIRMED:
            raise VideoPlanConflictError("配音尚未确认")
        if subtitle is None or subtitle.status != SUBTITLE_CONFIRMED:
            raise VideoPlanConflictError("字幕尚未确认")
        main_image = self._main_images.latest(session, project_id)
        if main_image is None or not main_image.version.transparent_object_key:
            raise VideoPlanConflictError("已确认主图不可用")
                # 短版（2026-10-15）：成片时长**以分镜总时长为准**，不再跟随配音 —— 两者曾经都是 18 秒所以没暴露，
        # 短版下配音 13.1s / 分镜 14s 会不一致，交付门的"成片规格"检查会判 fail（GATE_FAILED）。
        duration = self._storyboard_seconds(session, project_id) or min(25.0, max(8.0, voice_view.run.duration_seconds or 14.0))
        now = self._clock.now()
        plan = VideoPlan(
            id=new_id("vid"),
            project_id=project_id,
            mode=mode,
            template_id=template_id,
            status=PLAN_READY,
            duration_seconds=duration,
            width=1080,
            height=1920,
            fps=30,
            voice_enabled=voice_view.run.enabled,
            subtitle_enabled=subtitle.enabled,
            main_image_object_key=main_image.version.transparent_object_key,
            voice_object_key=voice_view.run.audio_object_key if voice_view.run.enabled else None,
            subtitle_object_key=subtitle.srt_object_key if subtitle.enabled else None,
            base_video_object_key=None,
            final_object_key=None,
            provider=self._composition.provider_name,
            error_code=None,
            created_at=now,
            updated_at=now,
            completed_at=None,
            confirmed_at=None,
            path=resolved_path,
            # 口径 5：新项目默认 auto（老项目走 DB 的 server_default='off'）
            motion_realism=MOTION_REALISM_AUTO,
            seam_mode=SEAM_PIN,
        )
        self._repository.add(session, plan)
        self._pipeline.mark_video_plan_ready(session, project_id)
        self._outbox.enqueue(session, event_name="VideoPlanCreated", aggregate_type="video_plan", aggregate_id=plan.id, occurred_at=now, payload={"project_id": project_id, "plan_id": plan.id, "mode": mode, "path": resolved_path})
        session.commit()
        return self._view(plan)

    def update_settings(
        self, session: Session, *, project_id: str,
        motion_realism: str | None = None, seam_mode: str | None = None,
        caption_style: object = KEEP, bgm_enabled: object = KEEP, bgm_gain_db: object = KEEP,
    ) -> VideoView:
        """导演模式的"免费旋钮"：提示词真实感档 / 接缝模式。

        - 只动方案上这两个字段：**不触发生成、不花钱**；
        - `seam_mode` 会改变 **kf2v / i2v 条数** → 预估变 → `payload_hash` 变 →
          **旧费用批准自动失效**（见 `cost_approval_context` 的绑定口径）；
        - `motion_realism` 不影响金额 → 既有批准继续有效。
        """
        plan = self._repository.latest(session, project_id)
        if plan is None:
            raise VideoPlanNotFoundError("视频方案不存在")
        changes: dict[str, object] = {}
        if motion_realism is not None:
            if motion_realism not in MOTION_REALISM_TIERS:
                raise VideoPlanValidationError("真实感档必须是 auto / constraints / off")
            changes["motion_realism"] = motion_realism
        if seam_mode is not None:
            if seam_mode not in SEAM_MODES:
                raise VideoPlanValidationError("接缝模式必须是 pin / tail / off")
            changes["seam_mode"] = seam_mode
        if caption_style is not KEEP:
            if caption_style is None:
                changes["caption_style"] = None          # 显式 null = 清除覆盖（回跟随全局）
            else:
                # 未知样式**显式报错**（`resolve_caption_style` 不静默回落，避免「选了没生效」）
                try:
                    resolve_caption_style(str(caption_style))
                except CaptionStyleError as exc:
                    raise VideoPlanValidationError(str(exc)) from exc
                changes["caption_style"] = str(caption_style)
        if bgm_enabled is not KEEP:
            changes["bgm_enabled"] = None if bgm_enabled is None else bool(bgm_enabled)
        if bgm_gain_db is not KEEP:
            if bgm_gain_db is None:
                changes["bgm_gain_db"] = None
            elif not (-40.0 <= float(bgm_gain_db) <= 0.0):
                raise VideoPlanValidationError("BGM 强度必须在 -40 ~ 0 dB 之间")
            else:
                changes["bgm_gain_db"] = float(bgm_gain_db)
        if not changes:
            return self._view(plan)
        updated = replace(plan, updated_at=self._clock.now(), **changes)
        self._repository.update(session, updated)
        session.commit()
        return self._view(updated)

    def request_video(self, session: Session, project_id: str) -> VideoView:
        plan = self._repository.latest(session, project_id)
        if plan is None:
            raise VideoPlanNotFoundError("视频方案不存在")
        if plan.status in {VIDEO_GENERATING, VIDEO_READY, RENDERING}:
            return self._view(plan)
        active = self._jobs.find_active(session, project_id, "video")
        if active:
            return self._view(plan)
        pipeline = self._pipeline.mark_video_generating(session, project_id)
        job = self._jobs.create(
            session,
            project_id=project_id,
            pipeline_run_id=pipeline.id,
            job_type="video",
            provider=plan.provider,
            input_hash=hashlib.sha256(f"{plan.id}:{plan.mode}:{plan.template_id}".encode()).hexdigest(),
            idempotency_key=f"video:{project_id}:{plan.id}",
            reference_id=plan.id,
        )
        plan = replace(plan, status=VIDEO_GENERATING, updated_at=self._clock.now())
        self._repository.update(session, plan)
        session.commit()
        # 作业超时**必须可配**：one_shot 的全部 r2v 调用都在这一个作业里，硬编码 600 秒对 18s 脚本必然超时
        # （实测单次 10s 片段 438 秒）。默认 2400 见 config.video_job_timeout_seconds。
        settings = get_settings()
        try:
            get_queue("video").enqueue(
                "onetake_api.modules.video_plan.worker_tasks.run_video_job", job.id,
                job_id=job.id, job_timeout=settings.video_job_timeout_seconds,
            )
        except Exception as exc:
            self._jobs.mark_failed(session, job, "QUEUE_UNAVAILABLE")
            self._mark_failed(session, plan, "QUEUE_UNAVAILABLE")
            raise VideoPlanConflictError("视频任务提交失败") from exc
        return self._view(plan)

    def process_job(self, session: Session, job_id: str) -> VideoPlan:
        settings = get_settings()
        job = self._jobs.get(session, job_id)
        if not job or job.job_type != "video" or job.status not in {"queued", "running"}:
            raise VideoPlanNotFoundError("视频任务不存在或不可执行")
        plan = self._repository.get(session, job.reference_id)
        if plan is None:
            raise VideoPlanNotFoundError("视频方案不存在")
        job = self._jobs.mark_running(session, job)
        session.commit()
        try:
            main_image = b"".join(self.storage.read_object(object_key=plan.main_image_object_key))
            audio_bytes = b"".join(self.storage.read_object(object_key=plan.voice_object_key)) if plan.voice_enabled and plan.voice_object_key else None
            base_key = f"projects/{plan.project_id}/video/{plan.id}/base.mp4"
            # 幂等 + 不再重复烧钱：base 视频（最贵的那一步：r2v / i2v / kf2v）**已经生成过就直接复用**。
            # 2026-10-15 实测：一次作业在"去 AI 味"这一步崩了（本地 ffmpeg），而 base.mp4 早就生成好了 ——
            # 旧实现重试会**重新调用供应商**（又花 ¥10.8），实际只需要重跑本地后处理（0 元）。
            base_video = None
            if plan.base_video_object_key:
                try:
                    stored = b"".join(self.storage.read_object(object_key=plan.base_video_object_key))
                    base_video = stored or None
                    if base_video is not None:
                        logger.info(
                            "video job 复用已生成的 base 视频（跳过付费生成）| %s",
                            plan.base_video_object_key,
                            extra={"job_id": job.id, "project_id": plan.project_id, "stage": "video"},
                        )
                except Exception:  # noqa: BLE001 - 读不到就重新生成（保持原行为）
                    base_video = None
            if base_video is None:
                base_video = self._create_base_video(session, plan, main_image, audio_bytes)
                base_key = f"projects/{plan.project_id}/video/{plan.id}/base.mp4"
                self.storage.put_bytes(object_key=base_key, content=base_video, mime_type="video/mp4")
                plan = replace(plan, status=VIDEO_READY, base_video_object_key=base_key, updated_at=self._clock.now())
                self._repository.update(session, plan)
                self._pipeline.mark_video_ready(session, plan.project_id)
                session.commit()

            srt_bytes = b"".join(self.storage.read_object(object_key=plan.subtitle_object_key)) if plan.subtitle_enabled and plan.subtitle_object_key else None
            plan = replace(plan, status=RENDERING, updated_at=self._clock.now())
            self._repository.update(session, plan)
            self._pipeline.mark_rendering(session, plan.project_id)
            session.commit()

            # 若已决定保留模型原声，则不再混入 TTS（否则双声）
            compose_audio = None if (settings.video_keep_model_audio and getattr(plan, "path", PATH_SEGMENTED) == PATH_ONE_SHOT) else audio_bytes
            final_video = self._composition.compose(CompositionRequest(
                base_video_bytes=base_video,
                audio_bytes=compose_audio,
                srt_bytes=srt_bytes,
                duration_seconds=plan.duration_seconds,
                width=plan.width,
                height=plan.height,
                fps=plan.fps,
                motion_effect=None,
                caption_style=plan.caption_style, bgm_enabled=plan.bgm_enabled, bgm_gain_db=plan.bgm_gain_db,
            ))
            metadata = validate_final_video(
                final_video,
                expected_width=plan.width,
                expected_height=plan.height,
                expected_fps=plan.fps,
                expected_audio=audio_bytes is not None,
            )
            qa_report = self._content_qa.evaluate_candidate(
                session,
                project_id=plan.project_id,
                video_plan_id=plan.id,
                video_bytes=final_video,
                metadata=metadata,
                expected_audio=audio_bytes is not None,
                subtitle_embedded=srt_bytes is not None,
                product_layered=True,
                product_image_bytes=main_image,
            )
            # Phase 5：抽帧拼图（真实拼接点）+ 交付门（质检 + 合规 + AIGC 标识断言）
            contact_sheet_url = self._store_contact_sheet(session, plan, final_video)
            gate = build_gate_report(
                session, project_id=plan.project_id, video_bytes=final_video,
                contact_sheet_url=contact_sheet_url, width=plan.width, height=plan.height,
                composition_provider=plan.provider,
                # 批次 1b：把"实际烧上去的那份 SRT"传给交付门的字幕安全区检查
                srt_bytes=srt_bytes,
            )
            gate_payload = asdict(gate)

            if gate.status == "fail":
                candidate_key = f"projects/{plan.project_id}/quality/{plan.id}/candidate.mp4"
                self.storage.put_bytes(object_key=candidate_key, content=final_video, mime_type="video/mp4")
                self._jobs.mark_failed(session, job, "GATE_FAILED")
                failed = replace(
                    plan, status=FAILED, error_code="GATE_FAILED",
                    gate_report=gate_payload,
                    updated_at=self._clock.now(), completed_at=self._clock.now(),
                )
                self._repository.update(session, failed)
                session.commit()
                return failed

            final_key = f"projects/{plan.project_id}/output/{plan.id}/final.mp4"
            self.storage.put_bytes(object_key=final_key, content=final_video, mime_type="video/mp4")
            now = self._clock.now()
            # 新成片产生后，旧的警告确认必须失效
            GateAckRepository().clear_for_project(session, plan.project_id)
            plan = replace(
                plan, status=COMPLETED, final_object_key=final_key, error_code=None,
                gate_report=gate_payload, updated_at=now, completed_at=now,
            )
            self._repository.update(session, plan)
            self._outputs.add(session, OutputArtifact(
                new_id("out"), plan.project_id, "video", final_key, "video/mp4", len(final_video), plan.duration_seconds,
                now, now + timedelta(seconds=OUTPUT_URL_SECONDS), metadata.width, metadata.height, metadata.fps,
                metadata.video_codec, metadata.audio_codec,
            ))
            self._jobs.mark_succeeded(session, job)
            self._pipeline.mark_completed(session, plan.project_id)
            self._outbox.enqueue(session, event_name="VideoCompleted", aggregate_type="output", aggregate_id=plan.id, occurred_at=now, payload={"project_id": plan.project_id, "plan_id": plan.id, "object_key": final_key, "size_bytes": len(final_video)})
            session.commit()
            return plan
        except DomainError as exc:
            # 必须把**供应商/适配器的原文**记下来：2026-10-15 实测一次 r2v 失败只留了 WAN_R2V_ERROR，
            # 供应商到底说什么（尺寸不符？任务 FAILED？超时？）全部丢失 → 无法定位，只能靠猜。
            logger.warning(
                "video job failed | code=%s | %s", exc.code, exc,
                extra={"job_id": job.id, "project_id": plan.project_id, "error_code": exc.code, "stage": "video"},
            )
            self._jobs.mark_failed(session, job, exc.code)
            return self._mark_failed(session, plan, exc.code)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "video job crashed | %s", exc,
                extra={"job_id": job.id, "project_id": plan.project_id, "error_code": "VIDEO_PROVIDER_ERROR", "stage": "video"},
            )
            self._jobs.mark_failed(session, job, "VIDEO_PROVIDER_ERROR")
            return self._mark_failed(session, plan, "VIDEO_PROVIDER_ERROR")

    def _create_base_video(self, session: Session, plan: VideoPlan, main_image: bytes, audio_bytes: bytes | None) -> bytes:
        settings = get_settings()

        if plan.mode == "product":
            if getattr(plan, "path", PATH_SEGMENTED) == PATH_ONE_SHOT:
                errors = self._one_shot_config_errors(settings)
                if errors:
                    raise VideoPlanConflictError("整片一次生成链路配置不完整：" + "；".join(errors))
                return self._create_one_shot_video(session, plan)
            return render_base_video(
                image_bytes=main_image,
                mode=plan.mode,
                template_id=plan.template_id,
                duration_seconds=plan.duration_seconds,
                width=plan.width,
                height=plan.height,
                fps=plan.fps,
            )

        raise VideoPlanValidationError("视频类型必须是有人或无人模式")


    @staticmethod
    def _silent_wav(duration_seconds: float) -> bytes:
        frame_rate = 48000
        frames = max(1, round(duration_seconds * frame_rate))
        output = BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(frame_rate)
            wav.writeframes(b"\x00\x00" * frames)
        return output.getvalue()
    def _store_contact_sheet(self, session: Session, plan: VideoPlan, video_bytes: bytes) -> str | None:
        """在真实拼接点抽帧拼图并返回可访问 URL。

        失败**不阻断**交付：交付门会补一条 warn（"抽帧拼图不可用"），由人来决定是否继续。
        """
        try:
            boundaries: list[float] = []
            content_plan = ContentPlanPublicService().latest(session, plan.project_id)
            if content_plan is not None and content_plan.variants:
                variant = content_plan.variants[content_plan.selected_variant_index]
                boundaries = [scene.end_seconds for scene in variant.scenes[:-1]]
            stamps = splice_timestamps(boundaries, duration_seconds=plan.duration_seconds)
            sheet = build_contact_sheet(video_bytes, timestamps=stamps)
            key = f"projects/{plan.project_id}/quality/{plan.id}/contact-sheet.png"
            self.storage.put_bytes(object_key=key, content=sheet, mime_type="image/png")
            return self.storage.create_get_url(object_key=key, expires_seconds=OUTPUT_URL_SECONDS).url
        except Exception:
            return None
    def _create_one_shot_video(self, session: Session, plan: VideoPlan) -> bytes:
        """整片一次生成（Phase 3）：多镜关键帧 → r2v 参考生视频，按 15s 上限自动切分后拼接。"""
        settings = get_settings()
        content_plan = ContentPlanPublicService().latest(session, plan.project_id)
        if content_plan is None or content_plan.status != CONTENT_PLAN_CONFIRMED:
            raise VideoPlanConflictError("请先确认视频分镜")
        variant = content_plan.variants[content_plan.selected_variant_index]
        keyframes = self._accepted_keyframes(session, plan.project_id)
        # 出镜人（人物库）：项目选了人就把母版当**身份锚点**一起喂（一次入库、每次出片复用、0 额外成本）
        character_sheet = self._character_sheet(session, plan.project_id)
        calls = plan_one_shot_calls(
            variant.scenes, max_seconds=settings.wan_r2v_max_seconds, has_character=character_sheet is not None,
        )
        clips = []
        for call in calls:
            refs = keyframe_refs_for_call(call, keyframes)
            if not refs:
                raise VideoPlanConflictError(f"第 {call.order} 次整片生成缺少已采用的关键帧，请先生成并确认关键帧")
            clips.append(self._generate_film_clip(plan, call, refs, character_sheet=character_sheet))
        # 整片路径可选择保留模型原声（口型台词）；默认仍丢弃、由 TTS 统一配音
        return concatenate_videos(
            clips=clips, duration_seconds=plan.duration_seconds, fps=plan.fps,
            keep_audio=settings.video_keep_model_audio,
        )

    def _character_sheet(self, session: Session, project_id: str) -> bytes | None:
        """项目的出镜人母版（人物库引用）。没选人就返回 None —— 不猜、不造。"""
        try:
            project = self._projects.get_project(session, project_id=project_id)
            character_id = getattr(project, "character_id", None)
            if not character_id:
                return None
            character = CharacterPublicService().get_character(session, character_id=character_id)
            return b"".join(self.storage.read_object(object_key=character.sheet_object_key)) or None
        except Exception:  # noqa: BLE001 - 母版读不到就如实当"没有"（不阻断出片）
            return None

    def _accepted_keyframes(self, session: Session, project_id: str) -> dict[str, bytes]:
        result: dict[str, bytes] = {}
        for candidate in self._keyframes.list_for_project(session, project_id):
            if candidate.status == KEYFRAME_ACCEPTED and candidate.image_object_key:
                result.setdefault(
                    candidate.scene_id, b"".join(self.storage.read_object(object_key=candidate.image_object_key))
                )
        return result

    def _generate_film_clip(self, plan: VideoPlan, call, refs: list[bytes], *, character_sheet: bytes | None = None) -> bytes:
        settings = get_settings()
        if settings.mock_providers or not settings.dashscope_api_key:
            # Mock：用首帧渲染一段确定性的同长度视频，端到端跑通同一条分支
            return render_base_video(
                image_bytes=refs[0],
                mode="product",
                template_id=plan.template_id or "clean",
                duration_seconds=call.duration_seconds,
                width=plan.width,
                height=plan.height,
                fps=plan.fps,
            )
        from onetake_api.integrations.wan_r2v.adapter import WanR2VAdapter

        uploader = DashScopeTemporaryUploader(api_key=settings.dashscope_api_key, model=settings.wan_r2v_model)
        # 期望尺寸必须按「请求的分辨率档位」推算，而不是成片尺寸：
        # 请求 720P 时供应商返回 720x1280，若按成片 1080x1920 校验会误报契约不符（钱白花）。
        tier_size = resolution_output_size(settings.wan_r2v_resolution) or (plan.width, plan.height)
        adapter = WanR2VAdapter(
            api_key=settings.dashscope_api_key,
            model=settings.wan_r2v_model,
            upload_media=lambda content, name: uploader.upload_image(content, name),
            resolution=settings.wan_r2v_resolution,
            max_seconds=settings.wan_r2v_max_seconds,
            expected_width=tier_size[0],
            expected_height=tier_size[1],
            # 单次最长生成时间（实测 10s 片段 ≈438s）→ 用配置的预算，别用适配器默认值
            poll_timeout_seconds=settings.wan_r2v_poll_timeout_seconds,
        )
        # media 顺序 = [各镜关键帧..., 出镜人母版]（母版编号 = 镜数 + 1，与 prompt 里写的一致）
        reference_images = list(refs[1:]) + ([character_sheet] if character_sheet else [])
        video_bytes, _task_id = adapter.generate_film(
            first_frame_bytes=refs[0],
            reference_images=reference_images,
            prompt=call.prompt,
            duration_seconds=call.duration_seconds,
        )
        return video_bytes

    @staticmethod
    def _one_shot_config_errors(settings: Settings) -> list[str]:
        if settings.mock_providers:
            return []
        errors: list[str] = []
        if not settings.dashscope_api_key:
            errors.append("缺少 DASHSCOPE_API_KEY")
        if not settings.wan_r2v_model:
            errors.append("缺少 WAN_R2V_MODEL")
        return errors
    @staticmethod
    def _split_segment_duration(duration_seconds: int, max_seconds: int) -> list[int]:
        max_seconds = max(1, max_seconds)
        if duration_seconds <= max_seconds:
            return [duration_seconds]
        count = math.ceil(duration_seconds / max_seconds)
        base, remainder = divmod(duration_seconds, count)
        return [base + (1 if index < remainder else 0) for index in range(count)]

    def _view(self, plan: VideoPlan | None) -> VideoView:
        if plan is None or not plan.final_object_key:
            return VideoView(plan=plan, video_url=None)
        url = self.storage.create_get_url(object_key=plan.final_object_key, expires_seconds=OUTPUT_URL_SECONDS).url
        return VideoView(plan=plan, video_url=url)

    def _mark_failed(self, session: Session, plan: VideoPlan, error_code: str) -> VideoPlan:
        now = self._clock.now()
        failed = replace(plan, status=FAILED, error_code=error_code, updated_at=now, completed_at=now)
        self._repository.update(session, failed)
        self._pipeline.mark_video_failed(session, plan.project_id)
        self._outbox.enqueue(session, event_name="VideoFailed", aggregate_type="video_plan", aggregate_id=plan.id, occurred_at=now, payload={"project_id": plan.project_id, "plan_id": plan.id, "error_code": error_code})
        session.commit()
        return failed
