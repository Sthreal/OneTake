"""关键帧视图（Phase 1）。

从「已确认分镜 + 已落库的关键帧候选」拼出前端需要的状态：
- 每个分镜一个槽位，带候选列表与已采用候选
- `generation_available` 反映"当前配置是否真的能生成"（mock 或已配置 DashScope Key），
  不能生成时前端应禁用入口，而不是点了才报错
本模块只产出领域状态，签名 URL 由 api 层负责。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from onetake_api.config import get_settings
from onetake_api.modules.content_plan.public import ContentPlanPublicService
from onetake_api.modules.video_plan.keyframe_domain import KEYFRAME_ACCEPTED, VideoKeyframeCandidate
from onetake_api.integrations.product_scene.keyframe_integrated import GRID_COLS, GRID_ROWS, MODE_GRID
from onetake_api.integrations.product_scene.keyframe_static_guard import static_warning
from onetake_api.modules.video_plan.keyframe_repository import VideoKeyframeCandidateRepository


@dataclass(frozen=True)
class KeyframeCandidateView:
    keyframe_id: str
    scene_id: str
    mode: str
    status: str
    image_object_key: str | None
    product_match: float | None
    text_intact: bool | None
    issues: list[str] = field(default_factory=list)
    fallback: str | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class KeyframeSlotView:
    scene_id: str
    order: int
    purpose: str
    visual_goal: str
    mode: str
    # S4a：关键帧提示词含时序词时的告警（规则在 S5 的 `keyframe_static_guard`，这里只透传结果）
    prompt_warning: str | None = None
    accepted: KeyframeCandidateView | None = None
    candidates: list[KeyframeCandidateView] = field(default_factory=list)


@dataclass(frozen=True)
class KeyframeStateView:
    project_id: str
    video_plan_id: str | None
    content_plan_id: str | None
    mode: str
    generation_available: bool
    candidates_per_call: int
    keyframes: list[KeyframeSlotView] = field(default_factory=list)
    # 九宫格整图（2026-10-15 加）：只回**对象键**，签名 URL 由 api 层负责（本模块不碰存储）
    grid_object_key: str | None = None


def _candidate_view(candidate: VideoKeyframeCandidate) -> KeyframeCandidateView:
    return KeyframeCandidateView(
        keyframe_id=candidate.id, scene_id=candidate.scene_id, mode=candidate.mode, status=candidate.status,
        image_object_key=candidate.image_object_key, product_match=candidate.product_match,
        text_intact=candidate.text_intact, issues=list(candidate.issues), fallback=candidate.fallback,
        error_code=candidate.error_code,
    )


def build_keyframe_state(session: Session, *, project_id: str) -> KeyframeStateView:
    settings = get_settings()
    plan = ContentPlanPublicService().latest(session, project_id)
    stored = VideoKeyframeCandidateRepository().list_for_project(session, project_id)
    by_scene: dict[str, list[VideoKeyframeCandidate]] = {}
    for candidate in stored:
        by_scene.setdefault(candidate.scene_id, []).append(candidate)

    if plan is None or not plan.variants:
        return KeyframeStateView(
            project_id=project_id, video_plan_id=None, content_plan_id=None,
            mode=settings.keyframe_mode, generation_available=False,
            candidates_per_call=settings.keyframe_candidates, keyframes=[],
        )

    variant = plan.variants[plan.selected_variant_index]
    slots: list[KeyframeSlotView] = []
    for scene in variant.scenes:
        scene_candidates = by_scene.get(scene.scene_id, [])
        accepted = next((item for item in scene_candidates if item.status == KEYFRAME_ACCEPTED), None)
        slots.append(KeyframeSlotView(
            scene_id=scene.scene_id, order=scene.order, purpose=scene.purpose,
            visual_goal=scene.visual_goal or "", mode=settings.keyframe_mode,
            prompt_warning=static_warning(scene.prompt),
            accepted=_candidate_view(accepted) if accepted else None,
            candidates=[_candidate_view(item) for item in scene_candidates],
        ))

    can_generate = settings.mock_providers or bool(settings.dashscope_api_key)
    # 九宫格整图的对象键（确定性路径，与 keyframe_service 生成时用的键一致）；
    # 只在"确实用过网格档"时给出，避免没生成过网格却返回一个 404 链接。
    used_grid = any(slot.accepted is not None and slot.accepted.mode == MODE_GRID for slot in slots) or any(
        any(item.mode == MODE_GRID for item in slot.candidates) for slot in slots
    )
    grid_object_key = (
        f"projects/{project_id}/keyframes/grid/{plan.id}/grid-{GRID_ROWS}x{GRID_COLS}.png" if used_grid else None
    )
    return KeyframeStateView(
        project_id=project_id, video_plan_id=None, content_plan_id=plan.id, mode=settings.keyframe_mode,
        generation_available=can_generate, candidates_per_call=settings.keyframe_candidates, keyframes=slots,
        grid_object_key=grid_object_key,
    )