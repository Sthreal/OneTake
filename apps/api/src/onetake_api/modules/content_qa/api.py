from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onetake_api.modules.content_qa.public import ContentQaPublicService
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


class QaResponse(BaseModel):
    data: QaReportData | None
    request_id: str


def _response(report) -> QaResponse:
    data = None if report is None else QaReportData(report_id=report.id, project_id=report.project_id, plan_id=report.plan_id, video_plan_id=report.video_plan_id, status=report.status, score=report.score, passed=report.passed, checks=[QaCheckData(**item.__dict__) for item in report.checks], critical_failures=report.critical_failures, provider=report.provider, model=report.model, created_at=report.created_at, rule_score=report.rule_score, semantic_score=report.semantic_score, semantic_checks=[QaCheckData(**item.__dict__) for item in report.semantic_checks], semantic_issues=report.semantic_issues)
    return QaResponse(data=data, request_id=get_request_id())


@router.get("", response_model=QaResponse)
def get_quality(project_id: str, session: Session = Depends(get_session)) -> QaResponse:
    return _response(ContentQaPublicService().latest(session, project_id))
