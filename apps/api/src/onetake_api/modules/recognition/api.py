from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onetake_api.modules.recognition.public import RecognitionPublicService
from onetake_api.platform.database import get_session
from onetake_api.platform.request_context import get_request_id

router = APIRouter(prefix="/api/v1/projects/{project_id}/recognition", tags=["recognition"])


class RecognitionRunData(BaseModel):
    run_id: str
    project_id: str
    status: str
    input_hash: str
    selected_asset_id: str | None
    selected_candidate_id: str | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class CandidateData(BaseModel):
    candidate_id: str
    run_id: str
    asset_id: str
    label: str
    confidence: float
    reason: str


class RecognitionData(BaseModel):
    run: RecognitionRunData | None
    candidates: list[CandidateData]


class RecognitionResponse(BaseModel):
    data: RecognitionData
    request_id: str


class ConfirmRecognitionRequest(BaseModel):
    asset_id: str
    candidate_id: str


def _run_data(run) -> RecognitionRunData:
    return RecognitionRunData(
        run_id=run.id, project_id=run.project_id, status=run.status, input_hash=run.input_hash,
        selected_asset_id=run.selected_asset_id, selected_candidate_id=run.selected_candidate_id,
        error_code=run.error_code, created_at=run.created_at, updated_at=run.updated_at,
        completed_at=run.completed_at,
    )


def _response(run, candidates) -> RecognitionResponse:
    return RecognitionResponse(
        data=RecognitionData(
            run=_run_data(run) if run else None,
            candidates=[CandidateData(candidate_id=c.id, run_id=c.run_id, asset_id=c.asset_id, label=c.label, confidence=c.confidence, reason=c.reason) for c in candidates],
        ),
        request_id=get_request_id(),
    )


@router.post("", response_model=RecognitionResponse, status_code=status.HTTP_202_ACCEPTED)
def request_recognition(project_id: str, session: Session = Depends(get_session)) -> RecognitionResponse:
    run = RecognitionPublicService().request(session, project_id)
    candidates = RecognitionPublicService().latest(session, project_id)[1]
    return _response(run, candidates)


@router.get("", response_model=RecognitionResponse)
def get_recognition(project_id: str, session: Session = Depends(get_session)) -> RecognitionResponse:
    run, candidates = RecognitionPublicService().latest(session, project_id)
    return _response(run, candidates)


@router.post("/{run_id}/confirm", response_model=RecognitionResponse)
def confirm_recognition(project_id: str, run_id: str, payload: ConfirmRecognitionRequest, session: Session = Depends(get_session)) -> RecognitionResponse:
    run = RecognitionPublicService().confirm(session, project_id, run_id, payload.candidate_id)
    _, candidates = RecognitionPublicService().latest(session, project_id)
    return _response(run, candidates)
