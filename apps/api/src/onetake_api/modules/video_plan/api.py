from __future__ import annotations

import logging
from dataclasses import asdict, replace
from datetime import datetime

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from onetake_api.integrations.media.model_capabilities import CAPABILITIES, preflight, resolve_model_kind
from onetake_api.modules.compliance.public import CompliancePublicService
from onetake_api.modules.content_qa.domain import RepairAction
from onetake_api.modules.content_qa.repair_plan import SegmentWindow
from onetake_api.modules.video_plan.repair_view import build_repair_actions
from onetake_api.modules.video_plan.segment_repository import VideoSegmentRepository
from onetake_api.modules.video_plan.domain import VideoPlan
from onetake_api.modules.video_plan.gate import GateCheckView, GateReportView, build_gate_report
from onetake_api.modules.video_plan.gate_ack_repository import GateAckRepository
from onetake_api.modules.video_plan.keyframe_public import VideoKeyframePublicService
from onetake_api.modules.video_plan.keyframe_view import KeyframeStateView, build_keyframe_state
from onetake_api.modules.video_plan.estimate import VideoGenerationEstimate
from onetake_api.modules.video_plan.public import VideoPlanPublicService
from onetake_api.modules.video_plan.segment_domain import VideoSegment, VideoSegmentCandidate
from onetake_api.modules.video_plan.segment_public import VideoSegmentPublicService
from onetake_api.modules.video_plan.segment_service import SegmentPlanMissingError, SegmentValidationError
from onetake_api.config import get_settings
from onetake_api.modules.script.public import ScriptPublicService
from onetake_api.modules.script.service import ScriptReviewRequiredError
from onetake_api.modules.video_plan.service import (
    KEEP,
    VideoPlanApplicationService,
    VideoPlanNotFoundError,
    VideoPlanValidationError,
    VideoView,
)
from onetake_api.platform.database import get_session
from onetake_api.platform.clock import SystemClock
from onetake_api.platform.errors import FeatureNotImplementedError
from onetake_api.platform.ids import new_id
from onetake_api.platform.request_context import get_request_id

router = APIRouter(prefix="/api/v1/projects/{project_id}", tags=["video"])
logger = logging.getLogger(__name__)


class CreateVideoPlanRequest(BaseModel):
    # 档位收敛（M4-04）：只接受 product。传 avatar 在 schema 层即被拒 → 422，
    # 不做静默降级（避免用户"以为还有数字人"）。
    mode: str = Field(pattern=r"^product$")
    template_id: str | None = Field(default=None, max_length=40)
    # 生成路径：不传时由服务端 GENERATION_PATH_DEFAULT 决定（MCP 等旧调用方零改动）
    path: str | None = Field(default=None, pattern=r"^(segmented|one_shot)$")


class UpdateVideoPlanSettingsRequest(BaseModel):
    """S6：导演模式的**免费旋钮**（改它们不触发任何生成、不花钱）。

    `seam_mode` 会改变 kf2v / i2v 的条数 → 预估变化 → `payload_hash` 变化 →
    **旧费用批准自动失效**（结构性保证，不需要额外代码）；`motion_realism` 不影响金额。
    """

    motion_realism: str | None = Field(default=None, pattern=r"^(auto|constraints|off)$")
    seam_mode: str | None = Field(default=None, pattern=r"^(pin|tail|off)$")
    # S4-④a：合成旋钮（免费重合成）。字幕样式在服务层用唯一真源校验（未知样式 422，不静默回落）
    caption_style: str | None = Field(default=None, max_length=20)
    bgm_enabled: bool | None = None
    bgm_gain_db: float | None = Field(default=None, ge=-40, le=0)


class VideoPlanData(BaseModel):
    plan_id: str
    seam_mode: str = "pin"
    project_id: str
    mode: str
    template_id: str | None
    status: str
    duration_seconds: float
    width: int
    height: int
    fps: int
    voice_enabled: bool
    subtitle_enabled: bool
    provider: str
    error_code: str | None
    video_url: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    batch_status: str
    batch_stop_requested: bool
    path: str = "segmented"
    motion_realism: str = "off"
    # S4-④a：方案级合成旋钮（None = 跟全局配置）
    caption_style: str | None = None
    bgm_enabled: bool | None = None
    bgm_gain_db: float | None = None


class VideoData(BaseModel):
    plan: VideoPlanData | None


class VideoResponse(BaseModel):
    data: VideoData
    request_id: str


class VideoEstimateData(BaseModel):
    plan_id: str
    mode: str
    template_id: str | None
    duration_seconds: float
    is_paid: bool
    wan_clip_count: int
    wan_generated_seconds: int
    qwen_image_edit_calls: int
    shotstack_renders: int
    estimated_wan_cost: float
    estimated_known_cost: float
    estimated_cost_max: float | None
    currency: str
    estimated_minutes: float
    confirmation_threshold: float
    requires_confirmation: bool
    missing_price_config: list[str]
    price_notes: list[str]
    path: str = "segmented"
    keyframe_calls: int = 0
    keyframe_images: int = 0
    i2v_clips: int = 0
    kf2v_clips: int = 0
    r2v_calls: int = 0
    r2v_seconds: int = 0
    composition: str = "shotstack"


class VideoEstimateResponse(BaseModel):
    data: VideoEstimateData
    request_id: str


def _data(plan: VideoPlan | None, video_url: str | None) -> VideoData:
    return VideoData(plan=VideoPlanData(
        plan_id=plan.id, project_id=plan.project_id, mode=plan.mode, template_id=plan.template_id,
        status=plan.status, duration_seconds=plan.duration_seconds, width=plan.width, height=plan.height,
        fps=plan.fps, voice_enabled=plan.voice_enabled, subtitle_enabled=plan.subtitle_enabled,
        provider=plan.provider, error_code=plan.error_code, video_url=video_url, created_at=plan.created_at,
        updated_at=plan.updated_at, completed_at=plan.completed_at, batch_status=plan.batch_status, batch_stop_requested=plan.batch_stop_requested, path=plan.path, motion_realism=plan.motion_realism,
        seam_mode=getattr(plan, "seam_mode", "pin"),
        caption_style=getattr(plan, "caption_style", None),
        bgm_enabled=getattr(plan, "bgm_enabled", None),
        bgm_gain_db=getattr(plan, "bgm_gain_db", None),
    ) if plan else None)


def _response(view: VideoView) -> VideoResponse:
    return VideoResponse(data=_data(view.plan, view.video_url), request_id=get_request_id())


def _require_cost_approval(session: Session, project_id: str, plan_id: str | None = None) -> None:
    """S8 硬约束：6 个付费入口共用的费用审批闸。

    放在**路由入口**而不是推进器内部 —— 人工点击、自动链、MCP 都从这 6 个入口进，
    因此都过同一道闸，不存在绕行路径。免费 / mock 的预估不设闸（见服务层）。
    """
    VideoPlanApplicationService().require_cost_approval(session, project_id=project_id, plan_id=plan_id)


def _require_script_review(session: Session, project_id: str) -> None:
    """花钱前的文案审稿闸。只拦「这份预估会付钱」的入口，不替代 cost_approvals。

    off：不看审稿。warn：未 apply/ack 只记日志。enforce：409 SCRIPT_REVIEW_REQUIRED，
    并且停在费用闸和任何 provider 调用之前。没有视频方案时与费用闸一样先放行，
    让原入口报自己的「方案不存在」。
    """
    mode = get_settings().script_review_gate
    if mode == "off":
        return
    try:
        context = VideoPlanApplicationService().cost_approval_context(session, project_id=project_id)
    except VideoPlanNotFoundError:
        return
    if not context.is_paid:
        return
    if ScriptPublicService().review_gate_passed(session, project_id):
        return
    if mode == "warn":
        logger.warning("审稿闸未通过（warn，不拦截付费视频）project_id=%s", project_id)
        return
    raise ScriptReviewRequiredError("付费视频前需要先完成文案审稿：应用改写或明确保留原稿")


def _require_paid_entry(session: Session, project_id: str, plan_id: str | None = None) -> None:
    """先审稿、再费用。两道闸都在 provider 之前。"""
    _require_script_review(session, project_id)
    _require_cost_approval(session, project_id, plan_id)


@router.patch("/video-plan", response_model=VideoResponse)
def update_video_plan_settings(
    project_id: str, payload: UpdateVideoPlanSettingsRequest, session: Session = Depends(get_session)
) -> VideoResponse:
    """只改免费旋钮；**不预扣、不生成、不花钱**。"""
    return _response(
        VideoPlanPublicService().update_settings(
            session, project_id=project_id, motion_realism=payload.motion_realism, seam_mode=payload.seam_mode,
            # **区分「没提」与「显式 null」**：没提 → KEEP（不动）；传了 null → 清除覆盖、回跟随全局
            caption_style=payload.caption_style if "caption_style" in payload.model_fields_set else KEEP,
            bgm_enabled=payload.bgm_enabled if "bgm_enabled" in payload.model_fields_set else KEEP,
            bgm_gain_db=payload.bgm_gain_db if "bgm_gain_db" in payload.model_fields_set else KEEP,
        )
    )


@router.get("/video-plan/{plan_id}/estimate", response_model=VideoEstimateResponse)
def estimate_video(project_id: str, plan_id: str, session: Session = Depends(get_session)) -> VideoEstimateResponse:
    estimate: VideoGenerationEstimate = VideoPlanPublicService().estimate(session, project_id=project_id, plan_id=plan_id)
    return VideoEstimateResponse(data=VideoEstimateData(**asdict(estimate)), request_id=get_request_id())


@router.post("/video-plan", response_model=VideoResponse, status_code=status.HTTP_201_CREATED)
def create_video_plan(project_id: str, payload: CreateVideoPlanRequest, session: Session = Depends(get_session)) -> VideoResponse:
    return _response(VideoPlanPublicService().create_plan(session, project_id=project_id, mode=payload.mode, template_id=payload.template_id, path=payload.path))


@router.get("/video", response_model=VideoResponse)
def get_video(project_id: str, session: Session = Depends(get_session)) -> VideoResponse:
    return _response(VideoPlanPublicService().latest(session, project_id))


@router.post("/video", response_model=VideoResponse, status_code=status.HTTP_202_ACCEPTED)
def request_video(project_id: str, session: Session = Depends(get_session)) -> VideoResponse:
    _require_paid_entry(session, project_id)
    return _response(VideoPlanPublicService().request_video(session, project_id))


@router.post("/compose", response_model=VideoResponse, status_code=status.HTTP_202_ACCEPTED)
def request_compose(project_id: str, session: Session = Depends(get_session)) -> VideoResponse:
    _require_paid_entry(session, project_id)
    return _response(VideoPlanPublicService().request_video(session, project_id))


class SegmentCandidateData(BaseModel):
    candidate_id: str
    segment_id: str
    order_index: int
    status: str
    provider: str
    anchor_source: str
    video_url: str | None
    tail_frame_url: str | None
    head_frame_url: str | None
    anchor_candidate_id: str | None
    duration_seconds: float | None
    width: int | None
    height: int | None
    fps: int | None
    # 症状式返修：本候选只针对该症状做了一次单变量修改
    symptom: str | None = None
    error_code: str | None
    created_at: datetime


class SegmentQualityData(BaseModel):
    """S6：该段的逐镜质量指标（时间线卡片直接可用）。数据各自可能为 None —— **不伪造**。"""

    # 该段对应分镜**已采纳关键帧**的质检结果（商品入画相似度 / 包装文字是否完好 / 是否走了像素锁回退）
    product_match: float | None = None
    text_intact: bool | None = None
    keyframe_fallback: str | None = None
    # 已采纳候选的实际时长与期望时长的差（正=比计划长）
    duration_delta_seconds: float | None = None
    # 该候选是不是"症状式单变量返修"的产物
    symptom: str | None = None


class SegmentData(BaseModel):

    segment_id: str
    plan_id: str
    order_index: int
    scene_id: str
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    status: str
    accepted_candidate_id: str | None
    last_error: str | None
    anchor_source: str | None
    # S4-③：段级接缝覆盖（None = 继承方案级）
    seam_mode: str | None = None
    # S2：本段「当前这条」的成片与首帧缩略图（取自已采纳候选）——
    # 时间线卡片要的是"这一段最终长什么样"，不必让前端自己在 candidates 里找 accepted。
    preview_url: str | None
    thumbnail_url: str | None
    quality: SegmentQualityData | None = None
    candidates: list[SegmentCandidateData]


class SegmentListData(BaseModel):
    plan_id: str | None
    segments: list[SegmentData]


class SegmentListResponse(BaseModel):
    data: SegmentListData
    request_id: str


def _candidate_url(object_key: str | None) -> str | None:
    if not object_key:
        return None
    try:
        from onetake_api.integrations.object_storage.dependencies import get_object_storage
        return get_object_storage().create_get_url(object_key=object_key, expires_seconds=3600).url
    except Exception:
        return None


def _candidate_data(candidate: VideoSegmentCandidate) -> SegmentCandidateData:
    return SegmentCandidateData(
        candidate_id=candidate.id, segment_id=candidate.segment_id, order_index=candidate.order_index,
        status=candidate.status, provider=candidate.provider, anchor_source=candidate.anchor_source,
        video_url=_candidate_url(candidate.video_object_key), tail_frame_url=_candidate_url(candidate.tail_frame_object_key),
        head_frame_url=_candidate_url(candidate.head_frame_object_key), anchor_candidate_id=candidate.anchor_candidate_id,
        duration_seconds=candidate.duration_seconds, width=candidate.width, height=candidate.height,
        fps=candidate.fps, symptom=candidate.symptom, error_code=candidate.error_code, created_at=candidate.created_at,
    )

def _accepted_keyframes_by_scene(session: Session, project_id: str) -> dict[str, object]:
    """一次查询取回本项目**全部已采纳关键帧**，按 scene_id 建索引（避免每段一次查询）。"""
    from onetake_api.modules.video_plan.keyframe_domain import KEYFRAME_ACCEPTED
    from onetake_api.modules.video_plan.keyframe_repository import VideoKeyframeCandidateRepository

    accepted: dict[str, object] = {}
    for candidate in VideoKeyframeCandidateRepository().list_for_project(session, project_id=project_id):
        if candidate.status == KEYFRAME_ACCEPTED and candidate.image_object_key:
            accepted[candidate.scene_id] = candidate
    return accepted


def _segment_data(segment: VideoSegment, keyframe: object | None = None) -> SegmentData:
    accepted = next((item for item in segment.candidates if item.id == segment.accepted_candidate_id), None)
    duration_delta = None
    if accepted is not None and accepted.duration_seconds is not None:
        duration_delta = round(float(accepted.duration_seconds) - float(segment.duration_seconds), 3)
    quality = SegmentQualityData(
        product_match=getattr(keyframe, "product_match", None),
        text_intact=getattr(keyframe, "text_intact", None),
        keyframe_fallback=getattr(keyframe, "fallback", None),
        duration_delta_seconds=duration_delta,
        symptom=accepted.symptom if accepted is not None else None,
    )
    return SegmentData(
        segment_id=segment.id, plan_id=segment.plan_id, order_index=segment.order_index, scene_id=segment.scene_id,
        start_seconds=segment.start_seconds, end_seconds=segment.end_seconds, duration_seconds=segment.duration_seconds,
        status=segment.status, accepted_candidate_id=segment.accepted_candidate_id, last_error=segment.last_error,
        anchor_source=accepted.anchor_source if accepted else None,
        seam_mode=getattr(segment, "seam_mode", None),
        preview_url=_candidate_url(accepted.video_object_key) if accepted else None,
        thumbnail_url=_candidate_url(accepted.head_frame_object_key) if accepted else None,
        candidates=[_candidate_data(item) for item in segment.candidates],
        quality=quality,
    )


def _segment_response(
    project_id: str,
    plan_id: str | None,
    segments: list[VideoSegment],
    *,
    keyframes_by_scene: dict[str, object] | None = None,
) -> SegmentListResponse:
    quality = keyframes_by_scene or {}
    return SegmentListResponse(
        data=SegmentListData(
            plan_id=plan_id,
            segments=[_segment_data(item, quality.get(item.scene_id)) for item in segments],
        ),
        request_id=get_request_id(),
    )


@router.get("/video/segments", response_model=SegmentListResponse)
def list_video_segments(project_id: str, plan_id: str | None = None, session: Session = Depends(get_session)) -> SegmentListResponse:
    segments = VideoSegmentPublicService().materialize_segments(session, project_id=project_id, plan_id=plan_id)
    resolved_plan_id = segments[0].plan_id if segments else plan_id
    return _segment_response(
        project_id, resolved_plan_id, segments,
        keyframes_by_scene=_accepted_keyframes_by_scene(session, project_id),
    )


@router.post("/video/segments/{segment_id}/candidates", response_model=SegmentListResponse, status_code=status.HTTP_201_CREATED)
def generate_segment_candidate(project_id: str, segment_id: str, payload: dict | None = None, session: Session = Depends(get_session)) -> SegmentListResponse:
    _require_paid_entry(session, project_id)
    seed = payload.get("seed") if isinstance(payload, dict) else None
    segments = VideoSegmentPublicService().generate_candidate(session, project_id=project_id, segment_id=segment_id, seed=seed)
    return _segment_response(
        project_id, segments[0].plan_id if segments else None, segments,
        keyframes_by_scene=_accepted_keyframes_by_scene(session, project_id),
    )


@router.post("/video/segments/{segment_id}/accept", response_model=SegmentListResponse)
def accept_segment_candidate(project_id: str, segment_id: str, payload: dict, session: Session = Depends(get_session)) -> SegmentListResponse:
    candidate_id = str(payload.get("candidate_id") or "")
    if not candidate_id:
        raise SegmentValidationError("缺少 candidate_id")
    segments = VideoSegmentPublicService().accept_candidate(session, project_id=project_id, candidate_id=candidate_id)
    return _segment_response(
        project_id, segments[0].plan_id if segments else None, segments,
        keyframes_by_scene=_accepted_keyframes_by_scene(session, project_id),
    )


@router.post("/video/segments/{segment_id}/reject", response_model=SegmentListResponse)
def reject_video_segment(project_id: str, segment_id: str, session: Session = Depends(get_session)) -> SegmentListResponse:
    segments = VideoSegmentPublicService().reject_segment(session, project_id=project_id, segment_id=segment_id)
    return _segment_response(
        project_id, segments[0].plan_id if segments else None, segments,
        keyframes_by_scene=_accepted_keyframes_by_scene(session, project_id),
    )


class SegmentSeamRequest(BaseModel):
    """段级接缝覆盖：`None` = 清除覆盖、继承方案级。"""

    seam_mode: str | None = Field(default=None, pattern=r"^(pin|tail|off)$")


@router.patch("/video/segments/{segment_id}/seam", response_model=SegmentListResponse)
def set_segment_seam(
    project_id: str, segment_id: str, payload: SegmentSeamRequest, session: Session = Depends(get_session)
) -> SegmentListResponse:
    """S4-③：段级接缝（方案 §3.2「每段卡片有该接缝处理方式」）。

    改它会改变该段 kf2v / i2v 的条数 → 费用预估随变 → 旧费用批准自动失效（预估已按段算）。
    **不触发生成、不花钱。**
    """
    segments = VideoSegmentPublicService().set_seam_mode(
        session, project_id=project_id, segment_id=segment_id, seam_mode=payload.seam_mode
    )
    return _segment_response(
        project_id, segments[0].plan_id if segments else None, segments,
        keyframes_by_scene=_accepted_keyframes_by_scene(session, project_id),
    )


@router.post("/video/batch", response_model=VideoResponse, status_code=status.HTTP_202_ACCEPTED)
def start_video_batch(
    project_id: str,
    # S2 步进：每次调用最多生成 N 段就返回（保持 running），**不传 = 旧的"一次跑完"行为**。
    stop_after_segments: int | None = Query(default=None, ge=1, le=50),
    session: Session = Depends(get_session),
) -> VideoResponse:
    _require_paid_entry(session, project_id)
    plan = VideoSegmentPublicService().start_batch(
        session, project_id=project_id, stop_after_segments=stop_after_segments
    )
    return _response(VideoView(plan=plan, video_url=None))


@router.post("/video/batch/stop", response_model=VideoResponse)
def stop_video_batch(project_id: str, session: Session = Depends(get_session)) -> VideoResponse:
    plan = VideoSegmentPublicService().stop_batch(session, project_id=project_id)
    return _response(VideoView(plan=plan, video_url=None))


# ==================== Phase 0 冻结契约：关键帧 / 交付门 / 合规 ====================
# 说明：Phase 0 只冻结接口与数据结构。关键帧生成（Phase 1）、症状返修（Phase 2）、
# 交付门确认（Phase 5）在能力上线前一律返回 501，绝不伪造成功结果。


class RetakeSegmentRequest(BaseModel):
    symptom: str = Field(pattern=r"^(product_warped|text_blurry|background_dead|light_wrong|blurry|object_drift)$")


class KeyframeCandidatesRequest(BaseModel):
    mode: str | None = Field(default=None, pattern=r"^(integrated|erase_background)$")
    n: int | None = Field(default=None, ge=1, le=6)
    seed: int | None = Field(default=None, ge=0)


class KeyframeAcceptRequest(BaseModel):
    keyframe_id: str = Field(min_length=1, max_length=80)


class KeyframeCandidateData(BaseModel):
    keyframe_id: str
    scene_id: str
    mode: str
    status: str
    image_url: str | None
    product_match: float | None
    text_intact: bool | None
    issues: list[str]
    fallback: str | None = None
    error_code: str | None = None


class KeyframeSlotData(BaseModel):
    scene_id: str
    order: int
    purpose: str
    visual_goal: str
    mode: str
    prompt_warning: str | None = None
    accepted: KeyframeCandidateData | None
    candidates: list[KeyframeCandidateData]


class KeyframeStateData(BaseModel):
    project_id: str
    video_plan_id: str | None
    content_plan_id: str | None
    mode: str
    generation_available: bool
    candidates_per_call: int
    grid_image_url: str | None = None
    grid_unusable: bool = False
    keyframes: list[KeyframeSlotData]


class KeyframeResponse(BaseModel):
    data: KeyframeStateData
    request_id: str


class GateCheckData(BaseModel):
    id: str
    level: str
    label: str
    message: str
    at_seconds: list[float]


class GateData(BaseModel):
    project_id: str
    status: str
    mode: str
    checks: list[GateCheckData]
    contact_sheet_url: str | None
    acknowledged: list[str]
    download_allowed: bool = True


class GateResponse(BaseModel):
    data: GateData
    request_id: str


class GateAckRequest(BaseModel):
    check_ids: list[str] = Field(min_length=1)


class BannedWordData(BaseModel):
    word: str
    where: str
    index: int


class PlatformWarningData(BaseModel):
    id: str
    message: str


class ComplianceData(BaseModel):
    project_id: str
    evaluated: bool
    rules_version: str
    aigc_label_enabled: bool
    aigc_label_text: str
    aigc_label_position: str
    aigc_label_source: str
    banned_words: list[BannedWordData]
    platform_warnings: list[PlatformWarningData]


class ComplianceResponse(BaseModel):
    data: ComplianceData
    request_id: str


def _keyframe_candidate_data(candidate) -> KeyframeCandidateData:
    return KeyframeCandidateData(
        keyframe_id=candidate.keyframe_id, scene_id=candidate.scene_id, mode=candidate.mode,
        status=candidate.status, image_url=_candidate_url(candidate.image_object_key),
        product_match=candidate.product_match, text_intact=candidate.text_intact,
        issues=list(candidate.issues), fallback=candidate.fallback, error_code=candidate.error_code,
    )


def _object_exists(storage, object_key: str) -> bool:
    """对象是否存在（存储层没有 exists API；读一次判，读失败一律当不存在）。"""
    try:
        return bool(b"".join(storage.read_object(object_key=object_key)))
    except Exception:  # noqa: BLE001
        return False


def _keyframe_state_data(view: KeyframeStateView) -> KeyframeStateData:
    # 九宫格整图：签名 URL（成片页「关键帧与九宫格」卡片用）。对象不存在就给 None，不给 404 链接。
    grid_image_url: str | None = None
    grid_unusable = False
    if view.grid_object_key:
        from onetake_api.integrations.object_storage.dependencies import get_object_storage

        storage = get_object_storage()
        grid_image_url = storage.create_get_url(
            object_key=view.grid_object_key, expires_seconds=3600,
        ).url if _object_exists(storage, view.grid_object_key) else None
        grid_unusable = _object_exists(storage, f"{view.grid_object_key}.unusable")
    return KeyframeStateData(
        project_id=view.project_id, video_plan_id=view.video_plan_id, content_plan_id=view.content_plan_id,
        mode=view.mode, generation_available=view.generation_available,
        candidates_per_call=view.candidates_per_call,
        grid_image_url=grid_image_url,
        grid_unusable=grid_unusable,
        keyframes=[
            KeyframeSlotData(
                scene_id=slot.scene_id, order=slot.order, purpose=slot.purpose, visual_goal=slot.visual_goal,
                mode=slot.mode,
                prompt_warning=slot.prompt_warning,
                accepted=_keyframe_candidate_data(slot.accepted) if slot.accepted else None,
                candidates=[_keyframe_candidate_data(item) for item in slot.candidates],
            )
            for slot in view.keyframes
        ],
    )

@router.get("/video/keyframes", response_model=KeyframeResponse)
def list_video_keyframes(project_id: str, session: Session = Depends(get_session)) -> KeyframeResponse:
    view = build_keyframe_state(session, project_id=project_id)
    return KeyframeResponse(data=_keyframe_state_data(view), request_id=get_request_id())


@router.post("/video/keyframes/{scene_id}/candidates", response_model=KeyframeResponse, status_code=status.HTTP_201_CREATED)
def generate_keyframe_candidates(project_id: str, scene_id: str, payload: KeyframeCandidatesRequest, session: Session = Depends(get_session)) -> KeyframeResponse:
    _require_paid_entry(session, project_id)
    VideoKeyframePublicService().generate_candidate(
        session, project_id=project_id, scene_id=scene_id, mode=payload.mode, n=payload.n, seed=payload.seed
    )
    view = build_keyframe_state(session, project_id=project_id)
    return KeyframeResponse(data=_keyframe_state_data(view), request_id=get_request_id())


@router.post("/video/keyframes/{scene_id}/accept", response_model=KeyframeResponse)
def accept_keyframe(project_id: str, scene_id: str, payload: KeyframeAcceptRequest, session: Session = Depends(get_session)) -> KeyframeResponse:
    VideoKeyframePublicService().accept_candidate(session, project_id=project_id, keyframe_id=payload.keyframe_id)
    view = build_keyframe_state(session, project_id=project_id)
    return KeyframeResponse(data=_keyframe_state_data(view), request_id=get_request_id())


@router.post("/video/segments/{segment_id}/retake", response_model=SegmentListResponse, status_code=status.HTTP_201_CREATED)
def retake_video_segment(project_id: str, segment_id: str, payload: RetakeSegmentRequest, session: Session = Depends(get_session)) -> SegmentListResponse:
    """症状式定向返修：一次只改一个变量，失败与费用纪律与常规生成一致。"""
    _require_paid_entry(session, project_id)
    segments = VideoSegmentPublicService().generate_candidate(
        session, project_id=project_id, segment_id=segment_id, symptom=payload.symptom
    )
    return _segment_response(
        project_id, segments[0].plan_id if segments else None, segments,
        keyframes_by_scene=_accepted_keyframes_by_scene(session, project_id),
    )


def _load_gate_view(session: Session, project_id: str) -> GateReportView:
    """优先读成片时落库的交付门结论；没有（旧方案）就现场算一份轻量结论。"""
    plan_view = VideoPlanPublicService().latest(session, project_id)
    plan = plan_view.plan
    payload = getattr(plan, "gate_report", None) if plan is not None else None
    if not payload:
        return build_gate_report(session, project_id=project_id)
    report = GateReportView(
        project_id=payload["project_id"],
        status=payload["status"],
        mode=payload["mode"],
        checks=[GateCheckView(**item) for item in payload.get("checks", [])],
        contact_sheet_url=payload.get("contact_sheet_url"),
        acknowledged=[],
        download_allowed=True,
    )
    acknowledged = GateAckRepository().list_for_project(session, project_id)
    pending = [check.id for check in report.checks if check.level == "warn" and check.id not in acknowledged]
    return replace(
        report,
        acknowledged=acknowledged,
        download_allowed=report.status != "fail" and not pending,
    )


@router.get("/video/gate", response_model=GateResponse)
def get_video_gate(project_id: str, session: Session = Depends(get_session)) -> GateResponse:
    view = _load_gate_view(session, project_id)
    return GateResponse(data=GateData(**asdict(view)), request_id=get_request_id())


@router.post("/video/gate/ack", response_model=GateResponse)
def acknowledge_video_gate(project_id: str, payload: GateAckRequest, session: Session = Depends(get_session)) -> GateResponse:
    """确认警告项：只能确认 warn，不能把 fail 确认掉（那是自欺）。"""
    view = _load_gate_view(session, project_id)
    warn_ids = {check.id for check in view.checks if check.level == "warn"}
    invalid = [check_id for check_id in payload.check_ids if check_id not in warn_ids]
    if invalid:
        raise VideoPlanValidationError("只能确认警告项：" + "、".join(invalid))
    repository = GateAckRepository()
    now = SystemClock().now()
    for check_id in payload.check_ids:
        repository.add(session, ack_id=new_id("ack"), project_id=project_id, check_id=check_id, created_at=now)
    session.commit()
    refreshed = _load_gate_view(session, project_id)
    return GateResponse(data=GateData(**asdict(refreshed)), request_id=get_request_id())


@router.get("/compliance", response_model=ComplianceResponse)
def get_compliance(project_id: str, session: Session = Depends(get_session)) -> ComplianceResponse:
    report = CompliancePublicService().report(session, project_id=project_id)
    return ComplianceResponse(data=ComplianceData(**asdict(report)), request_id=get_request_id())


# ==================== S6：修复计划 / 模型能力预检（两者都**只读**） ====================


class RepairActionData(BaseModel):
    check_id: str
    label: str
    level: str
    action: str
    reason: str
    target_ref: str | None = None
    estimated_cny: float | None = None
    execute_endpoint: str | None = None


class RepairPlanData(BaseModel):
    plan_id: str | None
    gate_status: str | None
    actions: list[RepairActionData]


class RepairPlanResponse(BaseModel):
    data: RepairPlanData
    request_id: str


class ModelCapabilityData(BaseModel):
    key: str
    label: str
    first_frame: bool
    last_frame: bool
    reference_images: int
    reference_video: bool
    max_call_seconds: int | None
    source: str


class PreflightCheckData(BaseModel):
    code: str
    level: str
    message: str


class ModelPreflightData(BaseModel):
    model_kind: str
    capabilities: ModelCapabilityData
    checks: list[PreflightCheckData]


class ModelPreflightResponse(BaseModel):
    data: ModelPreflightData
    request_id: str


def _repair_action_data(action: RepairAction) -> RepairActionData:
    return RepairActionData(
        check_id=action.check_id, label=action.label, level=action.severity, action=action.action,
        reason=action.reason, target_ref=action.target_ref, estimated_cny=action.estimated_cny,
        execute_endpoint=action.execute_endpoint,
    )


class ComposeOptionData(BaseModel):
    id: str
    label: str


class BgmOptionData(BaseModel):
    gain_db_min: float
    gain_db_max: float
    default_enabled: bool
    default_gain_db: float


class ComposeOptionsData(BaseModel):
    caption_styles: list[ComposeOptionData]
    # 当前全局默认档（前端显示「跟全局（X）」用；不猜）
    default_caption_style: str
    bgm: BgmOptionData


class ComposeOptionsResponse(BaseModel):
    data: ComposeOptionsData
    request_id: str


@router.get("/video/compose-options", response_model=ComposeOptionsResponse)
def get_compose_options(project_id: str) -> ComposeOptionsResponse:
    """S4-④a：合成旋钮的**唯一真源**（字幕样式清单 + BGM 取值范围/默认值）。

    前端下拉直接读这里，不在前端再写一份（否则两边迟早漂移）。**只读、0 元**。
    """
    from onetake_api.integrations.media.caption_styles import CAPTION_STYLE_KEYS, CAPTION_STYLE_LABELS
    from onetake_api.config import get_settings

    settings = get_settings()
    default_style = str(getattr(settings, "caption_style", "standard"))
    return ComposeOptionsResponse(
        data=ComposeOptionsData(
            caption_styles=[
                ComposeOptionData(id=key, label=CAPTION_STYLE_LABELS.get(key, key)) for key in CAPTION_STYLE_KEYS
            ],
            default_caption_style=default_style,
            bgm=BgmOptionData(
                gain_db_min=-40.0,
                gain_db_max=0.0,
                default_enabled=bool(getattr(settings, "bgm_enabled", False)),
                default_gain_db=float(getattr(settings, "bgm_gain_db", -20.0)),
            ),
        ),
        request_id=get_request_id(),
    )


@router.get("/video/repairs", response_model=RepairPlanResponse)
def list_video_repairs(project_id: str, session: Session = Depends(get_session)) -> RepairPlanResponse:
    """S6 6d：把交付门报告里的每条 warn/fail 翻成「下一步做什么」。

    **只读**：本端点不执行任何动作 —— 每个动作都可能付费，必须由人点（与 `repair_plan.py` 的
    「不提供一键全跑」是同一条纪律）。没有报告 / 没有 warn|fail 时返回空列表，**不编动作**。
    """
    plan = VideoPlanPublicService().latest(session, project_id).plan
    # 还没建方案 = 没有可修复的东西：明确 404（与 `/video/segments` 同一码），**不要** AttributeError→500
    # （2026-10-16 用户实测：新项目在分镜页每刷一次就吃两个 500）
    if plan is None:
        raise SegmentPlanMissingError("视频方案不存在")
    segments = VideoSegmentRepository().list_for_plan(session, plan.id)
    windows = [
        SegmentWindow(
            segment_id=item.id, start_seconds=item.start_seconds, end_seconds=item.end_seconds, scene_id=item.scene_id
        )
        for item in segments
    ]
    gate_report = plan.gate_report if isinstance(plan.gate_report, dict) else None
    actions = build_repair_actions(project_id=project_id, gate_report=gate_report, segments=windows)
    return RepairPlanResponse(
        data=RepairPlanData(
            plan_id=plan.id,
            gate_status=str((gate_report or {}).get("status", "")) or None,
            actions=[_repair_action_data(item) for item in actions],
        ),
        request_id=get_request_id(),
    )


@router.get("/video/model-preflight", response_model=ModelPreflightResponse)
def get_model_preflight(
    project_id: str,
    path: str | None = Query(default=None, pattern=r"^(segmented|one_shot)$"),
    seam_mode: str | None = Query(default=None, pattern=r"^(pin|tail|off)$"),
    session: Session = Depends(get_session),
) -> ModelPreflightResponse:
    """S6 6e：这次会走哪个模型、它支持什么、当前参数有什么降级。

    **只读**：不调用任何模型、不改任何状态；能力表的数据源是我们自己的适配器契约（见
    `integrations/media/model_capabilities.py` 的出处表）。
    """
    plan = VideoPlanPublicService().latest(session, project_id).plan
    if plan is None:
        raise SegmentPlanMissingError("视频方案不存在：模型预检要么先建方案，要么显式传 path")
    resolved_path = path or plan.path
    resolved_seam = seam_mode or getattr(plan, "seam_mode", "pin")
    kind = resolve_model_kind(path=resolved_path, seam_mode=resolved_seam)
    segments = VideoSegmentRepository().list_for_plan(session, plan.id)
    checks = preflight(
        model_kind=kind,
        duration_seconds=float(plan.duration_seconds),
        shot_count=len(segments) or 1,
        seam_mode=resolved_seam,
        path=resolved_path,
    )
    return ModelPreflightResponse(
        data=ModelPreflightData(
            model_kind=kind,
            capabilities=ModelCapabilityData(**asdict(CAPABILITIES[kind])),
            checks=[PreflightCheckData(code=item.code, level=item.level, message=item.message) for item in checks],
        ),
        request_id=get_request_id(),
    )
