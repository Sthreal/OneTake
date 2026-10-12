from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass

from onetake_api.integrations.media.video_utils import SegmentAnchor
from onetake_api.integrations.product_scene.style_profiles import get_style_profile
from onetake_api.integrations.wan_i2v.adapter import WanI2VAdapter, resolution_output_size
from onetake_api.modules.content_plan.domain import ContentScene
from onetake_api.modules.content_plan.prompt_schema import (
    build_background_negative_prompt,
    build_background_prompt,
    camera_move_phrase,
)
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
    camera = camera_move_phrase(scene.camera_move)
    action = (scene.subject_action or "").strip()
    if action and action not in base:
        base = f"{base} 主体动作：{action}。"
    if camera and camera not in base:
        base = f"{base} 运镜：{camera}。"
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


class MockSegmentAdapter:
    """MOCK_PROVIDERS 打开时的段级适配器：本地渲染，绝不触发真实付费调用。"""

    provider_name = "mock-i2v"

    def __init__(self, *, width: int, height: int, fps: int) -> None:
        self._width = width
        self._height = height
        self._fps = fps

    def generate(
        self,
        *,
        image_bytes: bytes,
        prompt: str,
        duration_seconds: int,
        negative_prompt: str | None = None,
    ) -> tuple[bytes, str]:
        from onetake_api.integrations.mock_video.renderer import render_base_video

        video = render_base_video(
            image_bytes=image_bytes,
            mode="product",
            template_id="clean",
            duration_seconds=float(max(1, int(duration_seconds))),
            width=self._width,
            height=self._height,
            fps=self._fps,
        )
        return video, "mock-segment"


def resolution_for_plan(plan: VideoPlan) -> str:
    """段级产物的分辨率档位由方案尺寸反推，而不是直接用全局 WAN_I2V_RESOLUTION。

    段产物尺寸必须等于成片规格：拼接（concatenate_videos）与最终校验
    （validate_final_video）都按 plan.width/height 断言，Provider 返回别的尺寸时整条链路都会失败。
    """
    return "1080P" if max(plan.width, plan.height) >= 1920 else "720P"


def _default_adapter(plan: VideoPlan) -> object:
    from onetake_api.config import get_settings
    from onetake_api.integrations.dashscope_uploader.adapter import DashScopeTemporaryUploader

    settings = get_settings()
    resolution = resolution_for_plan(plan)
    tier_size = resolution_output_size(resolution) or (plan.width, plan.height)
    # Mock 安全锁必须生效：旧路径在 MOCK_PROVIDERS 打开时根本不会走到 Wan I2V，
    # 段级路径之前却无条件构造真实适配器，会绕过安全锁直接产生付费调用。
    if settings.mock_providers:
        return MockSegmentAdapter(width=tier_size[0], height=tier_size[1], fps=plan.fps)
    uploader = DashScopeTemporaryUploader(api_key=settings.dashscope_api_key, model=settings.wan_i2v_model)
    return WanI2VAdapter(
        api_key=settings.dashscope_api_key,
        model=settings.wan_i2v_model,
        resolution=resolution,
        max_seconds=settings.wan_i2v_max_seconds,
        upload_image=lambda content: uploader.upload_image(content, "wan-segment-anchor.png"),
        # 契约按「该档位应有的输出尺寸」校验；档位是从方案尺寸反推的，因此等价于
        # 段产物必须等于成片规格（之前直接用全局 720P，Provider 只返回 720x1280 就必然违约）。
        expected_width=tier_size[0],
        expected_height=tier_size[1],
    )
