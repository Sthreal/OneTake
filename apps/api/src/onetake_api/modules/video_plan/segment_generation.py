from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass

from onetake_api.integrations.media.video_utils import SegmentAnchor
from onetake_api.integrations.media.video_utils import concatenate_videos, inspect_video_duration
from onetake_api.integrations.product_scene.style_profiles import get_style_profile
from onetake_api.integrations.wan_i2v.adapter import WanI2VAdapter, resolution_output_size
from onetake_api.modules.content_plan.domain import ContentScene
from onetake_api.modules.content_plan.prompt_schema import (
    build_background_negative_prompt,
    build_background_prompt,
    camera_move_phrase,
)
from onetake_api.modules.video_plan.domain import VideoPlan
from onetake_api.modules.video_plan.motion_prompt import (
    apply_symptom_patch,
    build_motion_negative_prompt,
    DEFAULT_REALISM,
    build_motion_prompt,
)
from onetake_api.modules.video_plan.segment_frame import SegmentTailFrameExtractor
from onetake_api.modules.video_plan.segment_repository import VideoSegmentCandidateRepository
from onetake_api.modules.video_plan.segment_plan import plan_segment_calls
from onetake_api.platform.errors import DomainError


# 切分后拼接的时长自检容差（秒）：这正是「静默钳制导致成片比配音短」那类缺陷的哨兵。
SEGMENT_DURATION_TOLERANCE_SECONDS = 0.5


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
    # 批次 4a：免 Key 素材的来源/许可/署名（None = 模型生成，无第三方署名义务）
    attribution: dict | None = None


def generate_seed() -> int:
    return random.randint(1, 2_000_000_000)


def assemble_segment_prompt(
    scene: ContentScene, plan: VideoPlan, *, seed: int | None = None, person_shot: bool | None = None
) -> str:
    """i2v 提示词：默认走 Phase 2 的运动提示词引擎，可开关回退到旧的静态背景描述。"""
    from onetake_api.config import get_settings

    if get_settings().video_motion_prompt_enabled:
        return build_motion_prompt(
            scene,
            product_visible=_product_visible(scene),
            seed=seed,
            # S5：真实感档（老项目 off / 新项目 auto）+ Look 光线锁（#10）
            realism=getattr(plan, "motion_realism", DEFAULT_REALISM),
            look=get_style_profile(plan.template_id),
            # 绑了出镜人时显式声明"这一镜有人"：默认的 detect_person_shot 是**关键词启发式**，
            # 而我们的分镜文本常常写着"无人物展示台" → 会判成没有人，人物惯性/衣发层全部不加。
            person_shot=person_shot,
        )
    style = get_style_profile(plan.template_id)
    return build_background_prompt(scene, style)


def _product_visible(scene: ContentScene) -> bool:
    mode = (scene.product_mode or "").strip()
    if mode in {"absent", "none"}:
        return False
    return bool(scene.overlay_product or mode)


def assemble_segment_negative_prompt(scene: ContentScene, plan: VideoPlan) -> str:
    """i2v 负向词：与正向词**同一个开关**分流（S7 提交 1）。

    开关开 → Phase 2 运动提示词引擎配套的**入画路线**词表（`build_motion_negative_prompt`）；
    开关关 → 旧背景路线词表（逐字保持改动前行为）。

    为什么要跟着开关走：改动前"正向词走 Phase 2 新引擎、负向词走**已废弃背景路线**词表" ——
    两边口径打架（一边要求商品入画，一边按"只生成背景"约束），负向词会与正向词互相抵消。
    背景路线的正/负向词必须**成对**回退，这也是 `assemble_segment_prompt` 的既有约定。
    """
    from onetake_api.config import get_settings

    if get_settings().video_motion_prompt_enabled:
        return build_motion_negative_prompt(scene)
    return build_background_negative_prompt(scene, get_style_profile(plan.template_id))


class SegmentVideoGenerator:
    """单段视频生成：解析锚点 -> 调 Wan I2V -> 抽取首尾帧。"""

    def __init__(
        self,
        *,
        storage,
        adapter_factory: Callable[[VideoPlan], object] | None = None,
        pair_adapter_factory: Callable[[VideoPlan], object] | None = None,
        frame_runner: SegmentTailFrameExtractor | None = None,
        candidate_repository: VideoSegmentCandidateRepository | None = None,
    ) -> None:
        self._storage = storage
        self._adapter_factory = adapter_factory or _default_adapter
        self._pair_adapter_factory = pair_adapter_factory or _default_pair_adapter
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
        symptom: str | None = None,
        person_shot: bool | None = None,
    ) -> GeneratedCandidate:
        prompt = assemble_segment_prompt(scene, plan, seed=seed, person_shot=person_shot)
        if symptom:
            # 单变量返修：只追加一条定向补丁，其余文案保持不变（便于定位到底什么修好了）
            prompt = apply_symptom_patch(prompt, symptom)

        from onetake_api.config import get_settings

        target = max(1, int(duration))
        # **分段 → 调用计划**：与预估共用同一张表（`segment_plan`）。
        # 改动前这里是一次调用 + 适配器把超限时长**静默钳到上限**（7 秒段只生成 5 秒，
        # 成片因此比配音短 2 秒）；现在超限就切成多次调用、子片段首尾相接再拼回来。
        calls = plan_segment_calls(
            duration_seconds=target,
            max_seconds=get_settings().wan_i2v_max_seconds,
            has_tail_frame=anchor.end_frame_bytes is not None,
        )
        if len(calls) == 1:
            # 单次可达：与改动前**逐字等价**（一条路径，不做额外拼接）
            video_bytes, provider_name = self._generate_clip(
                plan,
                head_bytes=anchor.frame_bytes,
                tail_bytes=anchor.end_frame_bytes if calls[0].pair else None,
                prompt=prompt,
                duration_seconds=calls[0].duration_seconds,
                negative_prompt=negative_prompt,
            )
        else:
            parts: list[bytes] = []
            head_bytes = anchor.frame_bytes
            provider_name = "wan-i2v"
            for call in calls:
                part, provider_name = self._generate_clip(
                    plan,
                    head_bytes=head_bytes,
                    tail_bytes=anchor.end_frame_bytes if call.pair else None,
                    prompt=prompt,
                    duration_seconds=call.duration_seconds,
                    negative_prompt=negative_prompt,
                )
                parts.append(part)
                # 子片段首尾相接：上一片的尾帧就是下一片的首帧（否则画面会直接跳到段末）
                head_bytes = self._frames.tail_frame(part)
            video_bytes = concatenate_videos(clips=parts, duration_seconds=target, fps=plan.fps)
            actual_seconds = inspect_video_duration(video_bytes)
            if abs(actual_seconds - target) > SEGMENT_DURATION_TOLERANCE_SECONDS:
                raise SegmentGenerationError(
                    f"分段切分后拼接时长 {actual_seconds:.2f}s 与目标 {target}s 不符"
                    f"（差 {abs(actual_seconds - target):.2f}s）"
                )
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
            duration_seconds=float(target), provider=provider_name,
        )

    def _generate_clip(
        self, plan: VideoPlan, *, head_bytes: bytes, tail_bytes: bytes | None,
        prompt: str, duration_seconds: int, negative_prompt: str,
    ) -> tuple[bytes, str]:
        """调一次供应商：有尾帧就走首尾帧对（kf2v），否则单帧（i2v）。

        **这是全仓唯一的"调一次段级供应商"入口** —— 单次路径与切分路径都从这里走，
        避免"单次走一套、切分走另一套"的漂移。
        """
        adapter = self._resolve_adapter(plan, pair=tail_bytes is not None)
        try:
            if tail_bytes is not None and hasattr(adapter, "generate_pair"):
                video_bytes, _task_id = adapter.generate_pair(
                    first_frame_bytes=head_bytes,
                    last_frame_bytes=tail_bytes,
                    prompt=prompt,
                    duration_seconds=max(1, int(duration_seconds)),
                    negative_prompt=negative_prompt,
                )
            else:
                video_bytes, _task_id = adapter.generate(
                    image_bytes=head_bytes,
                    prompt=prompt,
                    duration_seconds=max(1, int(duration_seconds)),
                    negative_prompt=negative_prompt,
                )
        except DomainError:
            raise
        except Exception as exc:
            raise SegmentGenerationError("分段视频生成失败") from exc
        if not video_bytes:
            raise SegmentGenerationError("分段视频生成返回空内容")
        return video_bytes, getattr(adapter, "provider_name", "wan-i2v")


    def _resolve_adapter(self, plan: VideoPlan, *, pair: bool):
        """需要首尾帧时优先拿「成对生成」适配器；拿不到就退回 i2v（不静默伪装成功）。"""
        if pair:
            candidate = self._pair_adapter_factory(plan)
            if candidate is not None and hasattr(candidate, "generate_pair"):
                return candidate
        return self._adapter_factory(plan)


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

    def generate_pair(
        self,
        *,
        first_frame_bytes: bytes,
        last_frame_bytes: bytes,
        prompt: str,
        duration_seconds: int,
        negative_prompt: str | None = None,
    ) -> tuple[bytes, str]:
        """Mock 的首尾帧路径：不调用任何付费服务，产出确定性的同款视频。"""
        return self.generate(
            image_bytes=first_frame_bytes, prompt=prompt,
            duration_seconds=duration_seconds, negative_prompt=negative_prompt,
        )


def resolution_for_plan(plan: VideoPlan) -> str:
    """段级产物的分辨率档位由方案尺寸反推，而不是直接用全局 WAN_I2V_RESOLUTION。

    段产物尺寸必须等于成片规格：拼接（concatenate_videos）与最终校验
    （validate_final_video）都按 plan.width/height 断言，Provider 返回别的尺寸时整条链路都会失败。
    """
    return "1080P" if max(plan.width, plan.height) >= 1920 else "720P"


def _default_pair_adapter(plan: VideoPlan) -> object | None:
    """首尾帧（kf2v）适配器工厂：未启用或缺配置时返回 None，由调用方回退 i2v。"""
    from onetake_api.config import get_settings
    from onetake_api.integrations.dashscope_uploader.adapter import DashScopeTemporaryUploader

    settings = get_settings()
    if not settings.video_kf2v_enabled:
        return None
    resolution = resolution_for_plan(plan)
    tier_size = resolution_output_size(resolution) or (plan.width, plan.height)
    if settings.mock_providers:
        return MockSegmentAdapter(width=tier_size[0], height=tier_size[1], fps=plan.fps)
    if not settings.wan_kf2v_model or not settings.dashscope_api_key:
        return None
    from onetake_api.integrations.wan_kf2v.adapter import WanKf2VAdapter

    uploader = DashScopeTemporaryUploader(api_key=settings.dashscope_api_key, model=settings.wan_kf2v_model)
    return WanKf2VAdapter(
        api_key=settings.dashscope_api_key,
        model=settings.wan_kf2v_model,
        resolution=resolution,
        max_seconds=settings.wan_i2v_max_seconds,
        upload_image=lambda content: uploader.upload_image(content, "wan-kf2v-frame.png"),
        expected_width=tier_size[0],
        expected_height=tier_size[1],
    )


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
