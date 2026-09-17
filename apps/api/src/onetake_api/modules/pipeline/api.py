from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onetake_api.modules.pipeline.public import PipelinePublicService
from onetake_api.platform.database import get_session
from onetake_api.platform.request_context import get_request_id

router = APIRouter(prefix="/api/v1/projects/{project_id}/pipeline", tags=["pipeline"])


class PipelineData(BaseModel):
    pipeline_run_id: str
    project_id: str
    status: str
    current_step: int
    state_version: int
    updated_at: datetime


class PipelineResponse(BaseModel):
    data: PipelineData
    request_id: str


@router.get("", response_model=PipelineResponse)
def get_pipeline(project_id: str, session: Session = Depends(get_session)) -> PipelineResponse:
    run = PipelinePublicService().get_or_create(session, project_id)
    return PipelineResponse(
        data=PipelineData(
            pipeline_run_id=run.id, project_id=run.project_id, status=run.status,
            current_step=run.current_step, state_version=run.state_version, updated_at=run.updated_at,
        ),
        request_id=get_request_id(),
    )
