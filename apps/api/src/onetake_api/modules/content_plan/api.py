from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from onetake_api.modules.content_plan.domain import ContentPlan
from onetake_api.modules.content_plan.prompt_schema import list_camera_options, list_product_mode_options, list_transition_options
from onetake_api.modules.content_plan.public import ContentPlanPublicService
from onetake_api.platform.database import get_session
from onetake_api.platform.request_context import get_request_id

router = APIRouter(prefix="/api/v1/projects/{project_id}/content-plan", tags=["content-plan"])


class SceneData(BaseModel):
    scene_id: str
    order: int
    purpose: str
    script_excerpt: str
    start_seconds: float
    end_seconds: float
    shot_type: str
    prompt: str
    overlay_product: bool
    product_position: str
    background_style: str
    template_id: str
    subtitle_segment_ids: list[int]
    qa_rules: list[str]
    # ---- 运动字段（Phase 0 起对前端可见，用于关键帧与镜头控制）----
    # 全部带默认值：老前端 payload 不带这些字段时仍可正常提交。
    visual_goal: str = ""
    subject_action: str = ""
    camera_move: str = "slow_push_in"
    product_mode: str = "overlay"
    transition: str = "fade"


class VariantData(BaseModel):
    variant_id: str
    name: str
    style: str
    scenes: list[SceneData]


class PlanData(BaseModel):
    plan_id: str
    project_id: str
    status: str
    provider: str
    model: str
    selected_variant_index: int
    total_duration_seconds: float
    variants: list[VariantData]
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None


class PlanResponse(BaseModel):
    data: PlanData | None
    request_id: str


class UpdatePlanRequest(BaseModel):
    selected_variant_index: int | None = Field(default=None, ge=0)
    scenes: list[SceneData] | None = None


def _data(plan: ContentPlan | None) -> PlanData | None:
    if plan is None:
        return None
    return PlanData(
        plan_id=plan.id, project_id=plan.project_id, status=plan.status, provider=plan.provider, model=plan.model,
        selected_variant_index=plan.selected_variant_index, total_duration_seconds=plan.total_duration_seconds,
        variants=[VariantData(variant_id=item.variant_id, name=item.name, style=item.style, scenes=[SceneData(**scene.__dict__) for scene in item.scenes]) for item in plan.variants],
        error_code=plan.error_code, created_at=plan.created_at, updated_at=plan.updated_at, confirmed_at=plan.confirmed_at,
    )


def _response(plan: ContentPlan | None) -> PlanResponse:
    return PlanResponse(data=_data(plan), request_id=get_request_id())


@router.get("", response_model=PlanResponse)
def get_plan(project_id: str, session: Session = Depends(get_session)) -> PlanResponse:
    return _response(ContentPlanPublicService().latest(session, project_id))


@router.post("", response_model=PlanResponse, status_code=status.HTTP_201_CREATED)
def generate_plan(project_id: str, session: Session = Depends(get_session)) -> PlanResponse:
    return _response(ContentPlanPublicService().generate(session, project_id))


@router.patch("", response_model=PlanResponse)
def update_plan(project_id: str, payload: UpdatePlanRequest, session: Session = Depends(get_session)) -> PlanResponse:
    return _response(ContentPlanPublicService().update(session, project_id=project_id, selected_variant_index=payload.selected_variant_index, scenes=[item.model_dump() for item in payload.scenes] if payload.scenes is not None else None))


class SceneCameraRequest(BaseModel):
    """逐镜运镜（导演模式）：接受**枚举键或自由文本**，长度上限 200（与逐镜内联编辑同一口径）。"""

    camera_move: str = Field(min_length=1, max_length=200)


@router.patch("/scene/{scene_id}/camera", response_model=PlanResponse)
def update_scene_camera(
    project_id: str, scene_id: str, payload: SceneCameraRequest, session: Session = Depends(get_session)
) -> PlanResponse:
    """**允许在方案已确认后**改单镜运镜（批量 `PATCH ""` 仍保持"已确认不可改"）。

    这是导演模式的逐镜控制入口；改动只影响**下一次生成该镜**，不触发任何付费调用、不改费用预估。
    """
    return _response(
        ContentPlanPublicService().update_scene_camera(
            session, project_id=project_id, scene_id=scene_id, camera_move=payload.camera_move
        )
    )


@router.post("/confirm", response_model=PlanResponse)
def confirm_plan(project_id: str, session: Session = Depends(get_session)) -> PlanResponse:
    return _response(ContentPlanPublicService().confirm(session, project_id))


# ==================== Phase 0 冻结契约：运动字段可选项 ====================


class CameraOptionData(BaseModel):
    id: str
    label: str


class ContentPlanOptionsData(BaseModel):
    camera_moves: list[CameraOptionData]
    transitions: list[CameraOptionData]
    product_modes: list[CameraOptionData]


class ContentPlanOptionsResponse(BaseModel):
    data: ContentPlanOptionsData
    request_id: str


@router.get("/options", response_model=ContentPlanOptionsResponse)
def get_content_plan_options() -> ContentPlanOptionsResponse:
    return ContentPlanOptionsResponse(
        data=ContentPlanOptionsData(
            camera_moves=[CameraOptionData(id=item_id, label=label) for item_id, label in list_camera_options()],
            transitions=[CameraOptionData(id=item_id, label=label) for item_id, label in list_transition_options()],
            product_modes=[CameraOptionData(id=item_id, label=label) for item_id, label in list_product_mode_options()],
        ),
        request_id=get_request_id(),
    )