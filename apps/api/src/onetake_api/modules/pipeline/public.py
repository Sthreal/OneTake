from __future__ import annotations

from dataclasses import replace

from sqlalchemy.orm import Session

from onetake_api.modules.pipeline.domain import (
    STATUS_ASSETS_READY,
    STATUS_FAILED,
    STATUS_IMAGE_EDITING,
    STATUS_MAIN_IMAGE_CONFIRMED,
    STATUS_MAIN_IMAGE_QUEUED,
    STATUS_MAIN_IMAGE_READY,
    STATUS_MATTING,
    STATUS_RECOGNITION_CONFIRMED,
    STATUS_RECOGNITION_READY,
    STATUS_RECOGNIZING,
    STATUS_SCRIPT_CONFIRMED,
    STATUS_SCRIPT_GENERATING,
    STATUS_SCRIPT_QUEUED,
    STATUS_SCRIPT_READY,
    STATUS_VOICE_GENERATING,
    STATUS_AUDIO_SUBTITLE_CONFIRMED,
    STATUS_CONTENT_PLAN_CONFIRMED,
    STATUS_CONTENT_PLAN_READY,
    STATUS_CONTENT_QA_FAILED,
    STATUS_CONTENT_QA_PASSED,
    STATUS_COMPLETED,
    STATUS_RENDERING,
    STATUS_SUBTITLE_GENERATING,
    STATUS_SUBTITLE_QUEUED,
    STATUS_SUBTITLE_READY,
    STATUS_VIDEO_GENERATING,
    STATUS_VIDEO_PLAN_READY,
    STATUS_VIDEO_READY,
    STATUS_VOICE_QUEUED,
    STATUS_VOICE_READY,
    PipelineRun,
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
        updated = replace(
            current,
            status=status,
            current_step=step,
            state_version=current.state_version + 1,
            updated_at=self._clock.now(),
        )
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

    def mark_main_image_failed(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_FAILED, 3)

    def mark_main_image_queued(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_MAIN_IMAGE_QUEUED, 3)

    def mark_image_editing(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_IMAGE_EDITING, 3)

    def mark_matting(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_MATTING, 3)

    def mark_main_image_ready(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_MAIN_IMAGE_READY, 3)

    def mark_main_image_confirmed(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_MAIN_IMAGE_CONFIRMED, 3)

    def mark_script_queued(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_SCRIPT_QUEUED, 3)

    def mark_script_generating(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_SCRIPT_GENERATING, 3)

    def mark_script_ready(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_SCRIPT_READY, 3)

    def mark_script_confirmed(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_SCRIPT_CONFIRMED, 4)

    def mark_script_failed(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_FAILED, 3)

    def mark_voice_queued(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_VOICE_QUEUED, 4)

    def mark_voice_generating(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_VOICE_GENERATING, 4)

    def mark_voice_ready(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_VOICE_READY, 4)

    def mark_voice_failed(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_FAILED, 4)

    def mark_subtitle_queued(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_SUBTITLE_QUEUED, 4)

    def mark_subtitle_generating(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_SUBTITLE_GENERATING, 4)

    def mark_subtitle_ready(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_SUBTITLE_READY, 4)

    def mark_subtitle_failed(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_FAILED, 4)

    def mark_audio_subtitle_confirmed(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_AUDIO_SUBTITLE_CONFIRMED, 4)

    def mark_video_plan_ready(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_VIDEO_PLAN_READY, 4)

    def mark_video_generating(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_VIDEO_GENERATING, 4)

    def mark_video_ready(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_VIDEO_READY, 4)

    def mark_rendering(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_RENDERING, 4)

    def mark_completed(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_COMPLETED, 4)

    def mark_video_failed(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_FAILED, 4)

    def mark_content_plan_ready(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_CONTENT_PLAN_READY, 4)

    def mark_content_plan_confirmed(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_CONTENT_PLAN_CONFIRMED, 4)

    def mark_content_qa_passed(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_CONTENT_QA_PASSED, 4)

    def mark_content_qa_failed(self, session: Session, project_id: str) -> PipelineRun:
        return self._transition(session, project_id, STATUS_CONTENT_QA_FAILED, 4)
