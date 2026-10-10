from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass

from onetake_api.integrations.media.video_utils import SegmentAnchor
from onetake_api.integrations.product_scene.style_profiles import get_style_profile
from onetake_api.integrations.wan_i2v.adapter import WanI2VAdapter
from onetake_api.modules.content_plan.domain import ContentScene
from onetake_api.modules.content_plan.prompt_schema import build_background_negative_prompt, build_background_prompt
from onetake_api.modules.video_plan.domain import VideoPlan
from onetake_api.modules.video_plan.segment_frame import SegmentTailFrameExtractor
from onetake_api.modules.video_plan.segment_repository import VideoSegmentCandidateRepository
from onetake_api.platform.errors import DomainError


class SegmentGenerationError(DomainError):
    code = "VIDEO_SEGMENT_GENERATION_FAILED"
    http_status = 502
    retryable = True


class SegmentContinuityError(DomainError):
    code = "PREVIOUS_SEGMENT_NOT_ACCEPTED"
    http_status = 409
    retryable = False


@dataclass(frozen=True)
class GeneratedCandidate:
    video_bytes: bytes
    tail_frame_bytes: bytes
    head_frame_bytes: bytes
    width: int
    height: int
    fps: int
    duration_seconds: float
    provider: str


def generate_seed() -> int:
    return random.randint(1, 2_000_000_000)


def assemble_segment_prompt(scene: ContentScene, plan: VideoPlan) -> str:
    style = get_style_profile(plan.template_id)
    base = build_background_prompt(scene, style)
    action = (scene.subject_action or "").strip()
    if action and action not in base:
        base = f"{base} 主体动作：{action}。"
    return base


def assemble_segment_negative_prompt(scene: ContentScene, plan: VideoPlan) -> str:
    return build_background_negative_prompt(scene, get_style_profile(plan.template_id))


class SegmentVideoGenerator:
    """单段视频生成：解析锚点 -> 调 Wan I2V -> 抽取首尾帧。"""

    def __init__(
        self,
        *,
        storage,
        adapter_factory: Callable[[VideoPlan], object] | None = None,
        frame_runner: SegmentTailFrameExtractor | None = None,
        candidate_repository: VideoSegmentCandidateRepository | None = None,
    ) -> None:
        self._storage = storage
        self._adapter_factory = adapter_factory or _default_adapter
        self._frames = frame_runner or SegmentTailFrameExtractor()
        self._candidates = candidate_repository or VideoSegmentCandidateRepository()

    def generate(
        self,
        *,
        plan: VideoPlan,
        segment,
        scene: ContentScene,
        anchor: SegmentAnchor,
        duration: int,
        seed: int,
        negative_prompt: str,
    ) -> GeneratedCandidate:
        adapter = self._adapter_factory(plan)
        prompt = assemble_segment_prompt(scene, plan)
        try:
            video_bytes, _task_id = adapter.generate(
                image_bytes=anchor.frame_bytes,
                prompt=prompt,
                duration_seconds=max(1, int(duration)),
                negative_prompt=negative_prompt,
            )
        except DomainError:
            raise
        except Exception as exc:
            raise SegmentGenerationError("分段视频生成失败") from exc
        if not video_bytes:
            raise SegmentGenerationError("分段视频生成返回空内容")
        try:
            tail = self._frames.tail_frame(video_bytes)
            head = self._frames.head_frame(video_bytes)
        except DomainError as exc:
            raise SegmentGenerationError(f"分段视频抽帧失败：{exc.message}") from exc
        width, height = _inspect_dimensions(video_bytes)
        return GeneratedCandidate(
            video_bytes=video_bytes, tail_frame_bytes=tail, head_frame_bytes=head,
            width=width, height=height, fps=plan.fps,
            duration_seconds=float(max(1, int(duration))), provider=getattr(adapter, "provider_name", "wan-i2v"),
        )


def _inspect_dimensions(video_bytes: bytes) -> tuple[int, int]:
    from onetake_api.integrations.media.video_utils import inspect_video_dimensions
    return inspect_video_dimensions(video_bytes)


def _default_adapter(plan: VideoPlan) -> WanI2VAdapter:
    from onetake_api.config import get_settings
    from onetake_api.integrations.dashscope_uploader.adapter import DashScopeTemporaryUploader

    settings = get_settings()
    uploader = DashScopeTemporaryUploader(api_key=settings.dashscope_api_key, model=settings.wan_i2v_model)
    return WanI2VAdapter(
        api_key=settings.dashscope_api_key,
        model=settings.wan_i2v_model,
        resolution=settings.wan_i2v_resolution,
        max_seconds=settings.wan_i2v_max_seconds,
        upload_image=lambda content: uploader.upload_image(content, "wan-segment-anchor.png"),
    )
