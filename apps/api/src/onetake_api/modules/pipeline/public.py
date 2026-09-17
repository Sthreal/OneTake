from __future__ import annotations

from dataclasses import replace

from sqlalchemy.orm import Session

from onetake_api.modules.pipeline.domain import (
    STATUS_ASSETS_READY, STATUS_FAILED, STATUS_RECOGNITION_CONFIRMED,
    STATUS_RECOGNITION_READY, STATUS_RECOGNIZING, PipelineRun,
)
from onetake_api.modules.pipeline.repository import PipelineRepository
from onetake_api.platform.clock import SystemClock
from onetake_api.platform.ids import new_id


class PipelinePublicService:
    def __init__(self) -> None:
        self._repository = PipelineRepository()
        self._clock = SystemClock()

    def get_or_create(self, session: Session, project_id: str) -> PipelineRun:
        run = self._repository.get(session, project_id)
        if run:
            return run
        now = self._clock.now()
        run = PipelineRun(new_id("run"), project_id, STATUS_ASSETS_READY, 1, 1, now, now)
        self._repository.add(session, run)
        session.flush()
        return run

    def _transition(self, session: Session, project_id: str, status: str, step: int) -> PipelineRun:
        current = self.get_or_create(session, project_id)
        updated = replace(current, status=status, current_step=step, state_version=current.state_version + 1, updated_at=self._clock.now())
        self._repository.update(session, updated)
        session.flush()
        return updated

    def mark_assets_ready(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_ASSETS_READY, 1)

    def mark_recognizing(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_RECOGNIZING, 2)

    def mark_recognition_ready(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_RECOGNITION_READY, 2)

    def mark_recognition_confirmed(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_RECOGNITION_CONFIRMED, 2)

    def mark_failed(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_FAILED, 2)
