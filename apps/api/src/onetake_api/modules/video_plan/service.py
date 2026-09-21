from __future__ import annotations

import hashlib
import math
from io import BytesIO
from pathlib import Path
import wave
from dataclasses import dataclass, replace
from datetime import timedelta

from sqlalchemy.orm import Session

from onetake_api.config import Settings, get_settings

from onetake_api.integrations.dashscope_uploader.adapter import DashScopeTemporaryUploader
from onetake_api.integrations.media.image_utils import add_contact_shadow
from onetake_api.integrations.media.video_utils import concatenate_videos
from onetake_api.integrations.mock_video.renderer import render_base_video, validate_final_video
from onetake_api.integrations.product_scene.scene_assets import load_scene_keyframe
from onetake_api.integrations.product_scene.style_profiles import apply_style_to_keyframe, get_style_profile
from onetake_api.modules.content_plan.prompt_schema import build_background_negative_prompt, build_background_prompt
from onetake_api.integrations.wan_i2v.adapter import WanI2VAdapter
from onetake_api.integrations.wan_s2v.adapter import WanS2VAdapter
from onetake_api.integrations.object_storage.dependencies import get_object_storage
from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.modules.composition.port import CompositionPort, CompositionRequest, ProductLayer
from onetake_api.modules.composition.service import get_composition_provider
from onetake_api.modules.content_plan.domain import STATUS_CONFIRMED as CONTENT_PLAN_CONFIRMED
from onetake_api.modules.content_plan.public import ContentPlanPublicService
from onetake_api.modules.content_qa.public import ContentQaPublicService
from onetake_api.modules.job.public import JobPublicService
from onetake_api.modules.main_image.public import MainImagePublicService
from onetake_api.modules.output.domain import OutputArtifact
from onetake_api.modules.output.repository import OutputRepository
from onetake_api.modules.outbox.public import OutboxPublicService
from onetake_api.modules.pipeline.public import PipelinePublicService
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.modules.subtitle.domain import SUBTITLE_CONFIRMED
from onetake_api.modules.subtitle.public import SubtitlePublicService
from onetake_api.modules.video_plan.domain import COMPLETED, FAILED, PLAN_READY, PRODUCT_SCENE_TEMPLATES, RENDERING, VIDEO_GENERATING, VIDEO_READY, VideoPlan
from onetake_api.modules.video_plan.estimate import VideoGenerationEstimate, estimate_video_generation
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
        return estimate_video_generation(plan, get_settings())

    def create_plan(self, session: Session, *, project_id: str, mode: str, template_id: str | None) -> VideoView:
        self._projects.get_project(session, project_id=project_id)
        if mode not in {"avatar", "product"}:
            raise VideoPlanValidationError("视频类型必须是有人或无人模式")
        if mode == "product" and template_id not in PRODUCT_SCENE_TEMPLATES:
            raise VideoPlanValidationError("无人模式必须选择有效模板")
        if mode == "avatar":
            template_id = None
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
        duration = min(25.0, max(18.0, voice_view.run.duration_seconds or 20.0))
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
        )
        self._repository.add(session, plan)
        self._pipeline.mark_video_plan_ready(session, project_id)
        self._outbox.enqueue(session, event_name="VideoPlanCreated", aggregate_type="video_plan", aggregate_id=plan.id, occurred_at=now, payload={"project_id": project_id, "plan_id": plan.id, "mode": mode})
        session.commit()
        return self._view(plan)

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
        try:
            get_queue("video").enqueue("onetake_api.modules.video_plan.worker_tasks.run_video_job", job.id, job_id=job.id, job_timeout=600)
        except Exception as exc:
            self._jobs.mark_failed(session, job, "QUEUE_UNAVAILABLE")
            self._mark_failed(session, plan, "QUEUE_UNAVAILABLE")
            raise VideoPlanConflictError("视频任务提交失败") from exc
        return self._view(plan)

    def process_job(self, session: Session, job_id: str) -> VideoPlan:
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

            uses_product_scene = self._uses_product_scene(plan)
            product_layers = self._product_layers(session, plan) if uses_product_scene else None
            product_image = add_contact_shadow(main_image) if uses_product_scene else main_image
            final_video = self._composition.compose(CompositionRequest(
                base_video_bytes=base_video,
                audio_bytes=audio_bytes,
                srt_bytes=srt_bytes,
                product_image_bytes=product_image,
                overlay_product=plan.mode == "avatar" or bool(product_layers),
                duration_seconds=plan.duration_seconds,
                width=plan.width,
                height=plan.height,
                fps=plan.fps,
                motion_effect=None,
                product_layers=product_layers,
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
            if not qa_report.passed:
                candidate_key = f"projects/{plan.project_id}/quality/{plan.id}/candidate.mp4"
                self.storage.put_bytes(object_key=candidate_key, content=final_video, mime_type="video/mp4")
                self._jobs.mark_failed(session, job, "CONTENT_QA_FAILED")
                failed = replace(plan, status=FAILED, error_code="CONTENT_QA_FAILED", updated_at=self._clock.now(), completed_at=self._clock.now())
                self._repository.update(session, failed)
                session.commit()
                return failed

            final_key = f"projects/{plan.project_id}/output/{plan.id}/final.mp4"
            self.storage.put_bytes(object_key=final_key, content=final_video, mime_type="video/mp4")
            now = self._clock.now()
            plan = replace(plan, status=COMPLETED, final_object_key=final_key, error_code=None, updated_at=now, completed_at=now)
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
            self._jobs.mark_failed(session, job, exc.code)
            return self._mark_failed(session, plan, exc.code)
        except Exception:
            self._jobs.mark_failed(session, job, "VIDEO_PROVIDER_ERROR")
            return self._mark_failed(session, plan, "VIDEO_PROVIDER_ERROR")

    def _create_base_video(self, session: Session, plan: VideoPlan, main_image: bytes, audio_bytes: bytes | None) -> bytes:
        settings = get_settings()
        if plan.mode == "avatar":
            if settings.avatar_video_provider == "real" and not settings.mock_providers:
                errors = self._avatar_video_config_errors(settings)
                if errors:
                    raise VideoPlanConflictError("有人视频真实链路配置不完整：" + "；".join(errors))
                return self._create_avatar_video(plan, audio_bytes)
            return render_base_video(
                image_bytes=main_image,
                mode=plan.mode,
                template_id=plan.template_id,
                duration_seconds=plan.duration_seconds,
                width=plan.width,
                height=plan.height,
                fps=plan.fps,
            )

        if plan.mode == "product":
            if plan.template_id in PRODUCT_SCENE_TEMPLATES and settings.product_scene_enabled and not settings.mock_providers:
                errors = self._product_scene_config_errors(settings)
                if errors:
                    raise VideoPlanConflictError("商品场景真实链路配置不完整：" + "；".join(errors))
                return self._create_product_scene_video(session, plan, main_image)
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

    def _create_avatar_video(self, plan: VideoPlan, audio_bytes: bytes | None) -> bytes:
        settings = get_settings()
        avatar_path = Path(settings.wan_s2v_avatar_path).expanduser()
        if not avatar_path.is_file():
            raise VideoPlanConflictError("WAN_S2V_AVATAR_PATH 指向的文件不存在")
        image_bytes = avatar_path.read_bytes()
        if not audio_bytes:
            audio_bytes = self._silent_wav(plan.duration_seconds)
        uploader = DashScopeTemporaryUploader(api_key=settings.dashscope_api_key, model=settings.wan_s2v_model)
        adapter = WanS2VAdapter(
            api_key=settings.dashscope_api_key,
            model=settings.wan_s2v_model,
            resolution=settings.wan_s2v_resolution,
            max_seconds=settings.wan_s2v_max_seconds,
            upload_image=lambda content: uploader.upload_image(content, "avatar.png"),
            upload_audio=lambda content: uploader.upload_audio(content, "voice.wav"),
        )
        video_bytes, _task_id = adapter.generate(
            image_bytes=image_bytes,
            audio_bytes=audio_bytes,
            prompt="固定数字人正面对镜口播，自然眨眼和轻微头部动作，保持人物身份稳定，不生成商品、文字或水印",
            duration_seconds=round(plan.duration_seconds),
        )
        return video_bytes

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

    @staticmethod
    def _avatar_video_config_errors(settings: Settings) -> list[str]:
        errors: list[str] = []
        if settings.mock_providers:
            errors.append("MOCK_PROVIDERS 必须为 false")
        if settings.avatar_video_provider != "real":
            errors.append("AVATAR_VIDEO_PROVIDER 必须为 real")
        if settings.composition_provider != "shotstack":
            errors.append("COMPOSITION_PROVIDER 必须为 shotstack")
        if not settings.dashscope_api_key:
            errors.append("缺少 DASHSCOPE_API_KEY")
        if not settings.wan_s2v_model:
            errors.append("缺少 WAN_S2V_MODEL")
        if not settings.wan_s2v_avatar_path:
            errors.append("缺少 WAN_S2V_AVATAR_PATH")
        if not settings.shotstack_api_key:
            errors.append("缺少 SHOTSTACK_API_KEY")
        return errors

    @staticmethod
    def _product_scene_config_errors(settings: Settings) -> list[str]:
        errors: list[str] = []
        if settings.mock_providers:
            errors.append("MOCK_PROVIDERS 必须为 false")
        if settings.image_edit_provider != "real":
            errors.append("IMAGE_EDIT_PROVIDER 必须为 real")
        if settings.wan_i2v_provider != "real":
            errors.append("WAN_I2V_PROVIDER 必须为 real")
        if settings.composition_provider != "shotstack":
            errors.append("COMPOSITION_PROVIDER 必须为 shotstack")
        if not settings.dashscope_api_key:
            errors.append("缺少 DASHSCOPE_API_KEY")
        if not settings.wan_i2v_model:
            errors.append("缺少 WAN_I2V_MODEL")
        if not settings.shotstack_api_key:
            errors.append("缺少 SHOTSTACK_API_KEY")
        return errors

    @staticmethod
    def _uses_product_scene(plan: VideoPlan) -> bool:
        settings = get_settings()
        return (
            settings.product_scene_enabled
            and plan.mode == "product"
            and plan.template_id in PRODUCT_SCENE_TEMPLATES
            and not VideoPlanApplicationService._product_scene_config_errors(settings)
        )

    def _product_layers(self, session: Session, plan: VideoPlan) -> list[ProductLayer] | None:
        content_plan = ContentPlanPublicService().latest(session, plan.project_id)
        if content_plan is None or content_plan.status != CONTENT_PLAN_CONFIRMED:
            raise VideoPlanConflictError("请先确认视频分镜")
        variant = content_plan.variants[content_plan.selected_variant_index]
        layers = []
        for scene in variant.scenes:
            if scene.product_mode == "absent":
                continue
            length = scene.end_seconds - scene.start_seconds
            if length <= 0:
                continue
            layers.append(ProductLayer(
                start=scene.start_seconds,
                length=length,
                effect="zoomIn" if scene.product_mode in {"overlay", "closeup"} else None,
            ))
        return layers

    def _create_product_scene_video(self, session: Session, plan: VideoPlan, main_image: bytes) -> bytes:
        if self._composition.provider_name == "mock-video":
            raise VideoPlanConflictError("商品场景视频需要 Shotstack 合成")
        content_plan = ContentPlanPublicService().latest(session, plan.project_id)
        if content_plan is None or content_plan.status != CONTENT_PLAN_CONFIRMED:
            raise VideoPlanConflictError("请先确认视频分镜")
        settings = get_settings()
        uploader = DashScopeTemporaryUploader(api_key=settings.dashscope_api_key, model=settings.wan_i2v_model)
        background_video = WanI2VAdapter(
            api_key=settings.dashscope_api_key,
            model=settings.wan_i2v_model,
            resolution=settings.wan_i2v_resolution,
            max_seconds=settings.wan_i2v_max_seconds,
            upload_image=lambda content: uploader.upload_image(content, "wan-background.png"),
        )
        variant = content_plan.variants[content_plan.selected_variant_index]
        clip_seconds = settings.wan_i2v_max_seconds
        style_profile = get_style_profile(plan.template_id)
        clips = []
        for scene in variant.scenes:
            keyframe = apply_style_to_keyframe(load_scene_keyframe(scene.visual_goal), style_profile)
            scene_seconds = max(1, round(scene.end_seconds - scene.start_seconds))
            for duration in self._split_segment_duration(scene_seconds, clip_seconds):
                prompt = build_background_prompt(scene, style_profile)
                negative_prompt = build_background_negative_prompt(scene, style_profile)
                video_bytes, _task_id = background_video.generate(
                    image_bytes=keyframe,
                    prompt=prompt,
                    duration_seconds=duration,
                    negative_prompt=negative_prompt,
                )
                clips.append(video_bytes)
        return concatenate_videos(clips=clips, duration_seconds=plan.duration_seconds, fps=plan.fps)

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
