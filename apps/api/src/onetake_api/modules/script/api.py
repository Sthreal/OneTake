from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from onetake_api.modules.script.domain import ScriptVersion
from onetake_api.modules.script.public import ScriptPublicService
from onetake_api.modules.script.service import ScriptView
from onetake_api.platform.database import get_session
from onetake_api.platform.request_context import get_request_id

router = APIRouter(prefix="/api/v1/projects/{project_id}/script", tags=["script"])


class GenerateScriptRequest(BaseModel):
    pain_point: str = Field(min_length=2, max_length=80)
    selling_points: list[str] = Field(min_length=1, max_length=5)
    usage_scenario: str = Field(min_length=2, max_length=100)
    offer: str | None = Field(default=None, max_length=80)


class EditScriptRequest(BaseModel):
    hook: str | None = Field(default=None, min_length=1, max_length=240)
    pain_point: str | None = Field(default=None, min_length=1, max_length=240)
    selling_points: list[str] | None = Field(default=None, min_length=1, max_length=5)
    usage_scenario: str | None = Field(default=None, min_length=1, max_length=300)
    cta: str | None = Field(default=None, min_length=1, max_length=240)


class ScriptFactsData(BaseModel):
    product_name: str
    product_note: str | None
    pain_point: str
    selling_points: list[str]
    usage_scenario: str
    offer: str | None


class ScriptVersionData(BaseModel):
    version_id: str
    project_id: str
    version_number: int
    status: str
    provider: str
    model: str
    facts: ScriptFactsData
    hook: str
    pain_point: str
    selling_points: list[str]
    usage_scenario: str
    offer: str | None
    cta: str
    full_text: str
    character_count: int
    estimated_duration_seconds: float
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    confirmed_at: datetime | None


class ScriptData(BaseModel):
    version: ScriptVersionData | None


class ScriptResponse(BaseModel):
    data: ScriptData
    request_id: str


def _version_data(version: ScriptVersion) -> ScriptVersionData:
    return ScriptVersionData(
        version_id=version.id,
        project_id=version.project_id,
        version_number=version.version_number,
        status=version.status,
        provider=version.provider,
        model=version.model,
        facts=ScriptFactsData(
            product_name=str(version.facts.get("product_name", "")),
            product_note=version.facts.get("product_note"),
            pain_point=str(version.facts.get("pain_point", "")),
            selling_points=list(version.facts.get("selling_points", [])),
            usage_scenario=str(version.facts.get("usage_scenario", "")),
            offer=version.facts.get("offer"),
        ),
        hook=version.hook,
        pain_point=version.pain_point,
        selling_points=version.selling_points,
        usage_scenario=version.usage_scenario,
        offer=version.offer,
        cta=version.cta,
        full_text=version.full_text,
        character_count=version.character_count,
        estimated_duration_seconds=version.estimated_duration_seconds,
        error_code=version.error_code,
        created_at=version.created_at,
        updated_at=version.updated_at,
        completed_at=version.completed_at,
        confirmed_at=version.confirmed_at,
    )


def _response(view: ScriptView) -> ScriptResponse:
    return ScriptResponse(
        data=ScriptData(version=_version_data(view.version) if view.version else None),
        request_id=get_request_id(),
    )


@router.get("", response_model=ScriptResponse)
def get_script(project_id: str, session: Session = Depends(get_session)) -> ScriptResponse:
    return _response(ScriptPublicService().latest(session, project_id))


@router.post("/generate", response_model=ScriptResponse, status_code=status.HTTP_202_ACCEPTED)
def generate_script(
    project_id: str,
    payload: GenerateScriptRequest,
    session: Session = Depends(get_session),
) -> ScriptResponse:
    view = ScriptPublicService().request(
        session,
        project_id=project_id,
        pain_point=payload.pain_point,
        selling_points=payload.selling_points,
        usage_scenario=payload.usage_scenario,
        offer=payload.offer,
    )
    return _response(view)


@router.patch("", response_model=ScriptResponse)
def edit_script(
    project_id: str,
    payload: EditScriptRequest,
    session: Session = Depends(get_session),
) -> ScriptResponse:
    view = ScriptPublicService().update(
        session,
        project_id=project_id,
        hook=payload.hook,
        pain_point=payload.pain_point,
        selling_points=payload.selling_points,
        usage_scenario=payload.usage_scenario,
        cta=payload.cta,
    )
    return _response(view)


@router.post("/confirm", response_model=ScriptResponse)
def confirm_script(project_id: str, session: Session = Depends(get_session)) -> ScriptResponse:
    return _response(ScriptPublicService().confirm(session, project_id))
