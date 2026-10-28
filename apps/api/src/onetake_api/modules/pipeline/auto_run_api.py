"""自动链与费用审批的 HTTP 入口（S8+S9+S10 提交 7）。

四个端点对应四件**已存在**的能力，这里只做暴露，不新增业务逻辑：

- `POST /projects/{id}/auto-run`   → 推进器 `resume_from_stage`（S9 一键编排 + 断点续跑）
- `GET  /auto-runs/{id}`           → 读断点、自动放行清单与当前状态（S8/S9 的审计面）
- `POST /auto-runs/{id}/stop`      → 协作式停止（在下个阶段边界干净停下）
- `POST /projects/{id}/cost-approval` → 登记「批准花钱」（S8 硬约束的另一半）

执行是**同步**的：中间免费段在 mock / 免费配置下是毫秒级动作，前端拿到响应就知道停在哪；
付费段由人工闸口② 拦住，不会在这里被自动触发。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from onetake_api.modules.pipeline.domain import PipelineRun
from onetake_api.modules.pipeline.orchestrator import AdvanceResult, PipelineOrchestrator
from onetake_api.modules.pipeline.public import PipelinePublicService
from onetake_api.modules.pipeline.repository import PipelineRepository
from onetake_api.modules.pipeline.stage_catalog import UnknownStageError
from onetake_api.modules.video_plan.service import VideoPlanApplicationService
from onetake_api.platform.database import get_session
from onetake_api.platform.errors import DomainError
from onetake_api.platform.request_context import get_request_id

router = APIRouter(prefix="/api/v1", tags=["auto-run"])

DEFAULT_FROM_STAGE = "recognition"


class PipelineRunNotFoundError(DomainError):
    code = "PIPELINE_RUN_NOT_FOUND"
    http_status = 404
    retryable = False


class AutoRunStageInvalidError(DomainError):
    """`from_stage` 不在阶段目录里 —— 明确 422，不静默从头跑。"""

    code = "AUTO_RUN_STAGE_INVALID"
    http_status = 422
    retryable = False


class AutoRunRequest(BaseModel):
    # 断点续跑的入口阶段；不传 = 从头（recognition）
    from_stage: str | None = Field(default=None, max_length=40)
    # 本次的预算（元）；不传 = 用服务端 AUTO_RUN_BUDGET_CNY（默认 0 = 只跑免费 / mock 阶段）
    budget_cny: float | None = Field(default=None, ge=0)


class AutoRunData(BaseModel):
    run_id: str
    project_id: str
    status: str
    stage: str | None
    auto_run: bool
    auto_confirmed_stages: list[str]
    auto_confirmed: list[str]
    stopped_at: str | None
    stopped_reason: str | None
    required_action: str | None


class AutoRunResponse(BaseModel):
    data: AutoRunData
    request_id: str


class StopAutoRunRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=120)


class StopAutoRunData(BaseModel):
    run_id: str
    in_flight: bool
    stop_requested: bool


class StopAutoRunResponse(BaseModel):
    data: StopAutoRunData
    request_id: str


class CostApprovalRequest(BaseModel):
    plan_id: str | None = Field(default=None, max_length=40)
    approved_by: str = Field(default="operator", max_length=40)


class CostApprovalData(BaseModel):
    plan_id: str
    is_paid: bool
    estimated_cny: float
    payload_hash: str
    approved_by: str


class CostApprovalResponse(BaseModel):
    data: CostApprovalData
    request_id: str


def _auto_run_data(run: PipelineRun, result: AdvanceResult | None) -> AutoRunData:
    return AutoRunData(
        run_id=run.id,
        project_id=run.project_id,
        status=run.status,
        stage=run.stage,
        auto_run=run.auto_run,
        auto_confirmed_stages=list(run.auto_confirmed_stages),
        auto_confirmed=list(result.auto_confirmed) if result else [],
        stopped_at=result.stopped_at if result else None,
        stopped_reason=result.stopped_reason if result else None,
        required_action=result.required_action if result else None,
    )


@router.post(
    "/projects/{project_id}/auto-run",
    response_model=AutoRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_auto_run(
    project_id: str, payload: AutoRunRequest, session: Session = Depends(get_session)
) -> AutoRunResponse:
    try:
        result = PipelineOrchestrator().resume_from_stage(
            session,
            project_id,
            payload.from_stage or DEFAULT_FROM_STAGE,
            budget_cny=payload.budget_cny,
        )
    except UnknownStageError as exc:
        # 阶段目录用 ValueError 表达「未知阶段」（纯数据层的语义）；HTTP 边界翻译成 422
        raise AutoRunStageInvalidError(str(exc)) from exc
    run = PipelinePublicService().get_or_create(session, project_id)
    return AutoRunResponse(data=_auto_run_data(run, result), request_id=get_request_id())


@router.get("/auto-runs/{run_id}", response_model=AutoRunResponse)
def get_auto_run(run_id: str, session: Session = Depends(get_session)) -> AutoRunResponse:
    run = PipelineRepository().get_by_id(session, run_id)
    if run is None:
        raise PipelineRunNotFoundError("自动链运行不存在")
    return AutoRunResponse(data=_auto_run_data(run, None), request_id=get_request_id())


@router.post("/auto-runs/{run_id}/stop", response_model=StopAutoRunResponse)
def stop_auto_run(
    run_id: str, payload: StopAutoRunRequest | None = None, session: Session = Depends(get_session)
) -> StopAutoRunResponse:
    """协作式停止：在跑的那一轮会在**下一个阶段边界**停下（不在事务中途硬中断）。

    不在跑（已经跑完 / 从未启动）时 `in_flight=false`、`stop_requested=false` —— 如实告知，
    不假装「已停止」。
    """
    orchestrator = PipelineOrchestrator()
    in_flight = orchestrator.request_stop(run_id)
    return StopAutoRunResponse(
        data=StopAutoRunData(run_id=run_id, in_flight=in_flight, stop_requested=in_flight),
        request_id=get_request_id(),
    )


@router.post("/projects/{project_id}/cost-approval", response_model=CostApprovalResponse)
def approve_cost(
    project_id: str, payload: CostApprovalRequest, session: Session = Depends(get_session)
) -> CostApprovalResponse:
    """登记一次「批准花钱」（幂等：同一份预估重复批准不重复落行）。"""
    context = VideoPlanApplicationService().approve_cost(
        session,
        project_id=project_id,
        plan_id=payload.plan_id,
        approved_by=payload.approved_by or "operator",
    )
    session.commit()
    return CostApprovalResponse(
        data=CostApprovalData(
            plan_id=context.plan_id,
            is_paid=context.is_paid,
            estimated_cny=context.estimated_cny,
            payload_hash=context.payload_hash,
            approved_by=payload.approved_by or "operator",
        ),
        request_id=get_request_id(),
    )