from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onetake_api.modules.content_plan.public import ContentPlanPublicService
from onetake_api.modules.content_qa.public import ContentQaPublicService
from onetake_api.modules.content_qa.repair_plan import (
    ACTION_LABELS,
    REPAIR_ACTIONS,
    SceneWindow,
    SegmentWindow,
    plan_repairs,
)
from onetake_api.modules.content_qa.service import ContentQaConflictError
from onetake_api.modules.content_qa.service import ContentQaConflictError
from onetake_api.modules.video_plan.gate import build_gate_report
from onetake_api.modules.video_plan.public import VideoPlanPublicService
from onetake_api.modules.video_plan.segment_public import VideoSegmentPublicService
from onetake_api.platform.errors import DomainError
from onetake_api.platform.database import get_session
from onetake_api.platform.request_context import get_request_id

router = APIRouter(prefix="/api/v1/projects/{project_id}/content-quality", tags=["content-quality"])


class QaCheckData(BaseModel):
    check_id: str
    label: str
    passed: bool
    weight: int
    message: str
    critical: bool
    # Phase 5：保留 passed 布尔（向后兼容），新增分级与命中时间点
    level: str = "ok"
    at_seconds: list[float] = []


class QaReportData(BaseModel):
    report_id: str
    project_id: str
    plan_id: str
    video_plan_id: str
    status: str
    score: int
    passed: bool
    checks: list[QaCheckData]
    critical_failures: list[str]
    provider: str
    model: str
    created_at: datetime
    rule_score: int | None
    semantic_score: int | None
    semantic_checks: list[QaCheckData]
    semantic_issues: list[str]
    # 客观信号（黑帧/静音/冻结/响度/时长），前端可直接展示
    signals: dict | None = None


class QaResponse(BaseModel):
    data: QaReportData | None
    request_id: str


def _response(report) -> QaResponse:
    data = None if report is None else QaReportData(report_id=report.id, project_id=report.project_id, plan_id=report.plan_id, video_plan_id=report.video_plan_id, status=report.status, score=report.score, passed=report.passed, checks=[QaCheckData(**item.__dict__) for item in report.checks], critical_failures=report.critical_failures, provider=report.provider, model=report.model, created_at=report.created_at, rule_score=report.rule_score, semantic_score=report.semantic_score, semantic_checks=[QaCheckData(**item.__dict__) for item in report.semantic_checks], semantic_issues=report.semantic_issues, signals=report.signals)
    return QaResponse(data=data, request_id=get_request_id())


@router.get("", response_model=QaResponse)
def get_quality(project_id: str, session: Session = Depends(get_session)) -> QaResponse:
    return _response(ContentQaPublicService().latest(session, project_id))


# ---------------------------------------------------------------- S11：修复动作计划
# 只读路由：把交付门的 warn|fail 翻成「下一步做什么」。**不新增任何写端点** ——
# 每个动作的 `execute_endpoint` 都指向既有端点，由前端/CLI 或人照着调。
class SegmentScoreData(BaseModel):
    segment_id: str
    order_index: int
    scene_id: str
    scores: dict[str, int]
    overall: int
    issues: list[str] = []
    evidence_seconds: list[float] = []


class SegmentQualityData(BaseModel):
    project_id: str
    plan_id: str
    provider: str
    model: str
    calls: int
    created_at: str
    low_score_threshold: int
    # DashScope 真实用量汇总（tokens）：用来校准单价（空 = 模型没返回用量）
    usage: dict[str, int] = {}
    segments: list[SegmentScoreData]


class SegmentQualityResponse(BaseModel):
    data: SegmentQualityData | None
    request_id: str


def _segment_quality_data(report) -> SegmentQualityData:
    payload = report.to_dict()
    return SegmentQualityData(
        project_id=payload["project_id"], plan_id=payload["plan_id"], provider=payload["provider"],
        model=payload["model"], calls=payload["calls"], created_at=payload["created_at"],
        low_score_threshold=payload["low_score_threshold"],
        usage=dict(payload.get("usage") or {}),
        segments=[SegmentScoreData(**item) for item in payload["segments"]],
    )


@router.get("/segments", response_model=SegmentQualityResponse)
def get_segment_quality(project_id: str, session: Session = Depends(get_session)) -> SegmentQualityResponse:
    """最近一次逐镜评分（没有就返回 null，不伪造）。"""
    from onetake_api.modules.content_qa import segment_quality

    report = segment_quality.read_report(project_id)
    return SegmentQualityResponse(
        data=None if report is None else _segment_quality_data(report), request_id=get_request_id()
    )


@router.post("/segments", response_model=SegmentQualityResponse)
def run_segment_quality(project_id: str, session: Session = Depends(get_session)) -> SegmentQualityResponse:
    """跑逐镜评分：**付费调用**，所以先过费用审批闸（与其它付费入口同一道闸）。"""
    from onetake_api.modules.content_qa.service import ContentQaApplicationService

    plan = getattr(VideoPlanPublicService().latest(session, project_id), "plan", None)
    if plan is None:
        raise ContentQaConflictError("还没有视频方案，无法逐镜评分")
    # 走**同一道费用闸**：VideoPlanApplicationService 的包装会从预估（含逐镜评分那几笔调用）算出
    # 金额与 payload_hash，再落到 PipelinePublicService —— 这里不自己算钱，避免第二套口径。
    from onetake_api.modules.video_plan.service import VideoPlanApplicationService

    VideoPlanApplicationService().require_cost_approval(session, project_id=project_id, plan_id=plan.id)
    report = ContentQaApplicationService().score_segments(session, project_id=project_id)
    return SegmentQualityResponse(data=_segment_quality_data(report), request_id=get_request_id())

repairs_router = APIRouter(prefix="/api/v1/projects/{project_id}", tags=["repairs"])


class RepairActionData(BaseModel):
    check_id: str
    label: str
    severity: str
    action: str
    action_label: str
    reason: str
    target_ref: str | None
    estimated_cny: float | None
    execute_endpoint: str | None


class RepairPlanData(BaseModel):
    project_id: str
    gate_status: str
    download_allowed: bool
    actions: list[RepairActionData]


class RepairResponse(BaseModel):
    data: RepairPlanData
    request_id: str


def _segment_windows(session: Session, project_id: str) -> list[SegmentWindow]:
    """分段定位窗口。没有视频方案（或尚未物化分段）时返回空 —— 不为了取窗口而新建方案。"""
    try:
        segments = VideoSegmentPublicService().materialize_segments(session, project_id=project_id)
    except DomainError:
        return []
    return [
        SegmentWindow(
            segment_id=segment.id,
            start_seconds=segment.start_seconds,
            end_seconds=segment.end_seconds,
            scene_id=segment.scene_id,
        )
        for segment in segments
    ]


def _scene_windows(session: Session, project_id: str) -> list[SceneWindow]:
    plan = ContentPlanPublicService().latest(session, project_id)
    if plan is None or not plan.variants:
        return []
    try:
        variant = plan.variants[plan.selected_variant_index]
    except IndexError:
        return []
    return [
        SceneWindow(scene_id=scene.scene_id, start_seconds=scene.start_seconds, end_seconds=scene.end_seconds)
        for scene in variant.scenes
    ]


def _action_costs(session: Session, project_id: str) -> dict[str, float]:
    """动作的费用上界（元）。视频类动作用**方案级预估**（同一份 `estimate.py`，不新增计价逻辑）；免费/mock 全 0。"""
    costs = {action: 0.0 for action in REPAIR_ACTIONS}
    try:
        view = VideoPlanPublicService().latest(session, project_id)
        if view.plan is None:
            return costs
        estimate = VideoPlanPublicService().estimate(session, project_id=project_id, plan_id=view.plan.id)
    except DomainError:
        return costs
    if not estimate.is_paid:
        return costs
    for action in ("retake_segment", "rebuild_segment", "regenerate_keyframe", "recompose"):
        costs[action] = estimate.estimated_known_cost
    return costs


@repairs_router.get("/repairs", response_model=RepairResponse)
def get_repairs(project_id: str, session: Session = Depends(get_session)) -> RepairResponse:
    report = build_gate_report(session, project_id=project_id)
    actions = plan_repairs(
        report,
        segments=_segment_windows(session, project_id),
        scenes=_scene_windows(session, project_id),
        action_cost_cny=_action_costs(session, project_id),
    )
    return RepairResponse(
        data=RepairPlanData(
            project_id=project_id,
            gate_status=report.status,
            download_allowed=report.download_allowed,
            actions=[
                RepairActionData(
                    check_id=item.check_id,
                    label=item.label,
                    severity=item.severity,
                    action=item.action,
                    action_label=ACTION_LABELS.get(item.action, item.action),
                    reason=item.reason,
                    target_ref=item.target_ref,
                    estimated_cny=item.estimated_cny,
                    execute_endpoint=item.execute_endpoint,
                )
                for item in actions
            ],
        ),
        request_id=get_request_id(),
    )
