from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from onetake_api.modules.content_plan.domain import ContentPlan
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


@router.post("/confirm", response_model=PlanResponse)
def confirm_plan(project_id: str, session: Session = Depends(get_session)) -> PlanResponse:
    return _response(ContentPlanPublicService().confirm(session, project_id))
