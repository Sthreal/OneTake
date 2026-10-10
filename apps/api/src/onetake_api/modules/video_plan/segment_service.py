from __future__ import annotations

from dataclasses import replace

from sqlalchemy.orm import Session

from onetake_api.modules.content_plan.domain import STATUS_CONFIRMED as CONTENT_PLAN_CONFIRMED
from onetake_api.modules.content_plan.domain import ContentPlan
from onetake_api.modules.content_plan.public import ContentPlanPublicService
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.modules.video_plan.domain import PRODUCT_SCENE_TEMPLATES, VideoPlan
from onetake_api.modules.video_plan.repository import VideoPlanRepository
from onetake_api.modules.video_plan.segment_domain import (
    CANDIDATE_ACCEPTED,
    CANDIDATE_REJECTED,
    SEGMENT_ACCEPTED,
    SEGMENT_AWAITING_REVIEW,
    SEGMENT_PLANNED,
    VideoSegment,
)
from onetake_api.modules.video_plan.segment_repository import (
    VideoSegmentCandidateRepository,
    VideoSegmentRepository,
)
from onetake_api.platform.clock import SystemClock
from onetake_api.platform.errors import DomainError
from onetake_api.platform.ids import new_id


class SegmentNotFoundError(DomainError):
    code = "VIDEO_SEGMENT_NOT_FOUND"
    http_status = 404


class SegmentConflictError(DomainError):
    code = "VIDEO_SEGMENT_CONFLICT"
    http_status = 409
    retryable = True


class SegmentValidationError(DomainError):
    code = "VIDEO_SEGMENT_VALIDATION_ERROR"
    http_status = 422


class SegmentPlanMissingError(DomainError):
    code = "VIDEO_PLAN_NOT_FOUND"
    http_status = 404


class SegmentPlanNotConfirmedError(DomainError):
    code = "CONTENT_PLAN_NOT_CONFIRMED"
    http_status = 409


class VideoSegmentApplicationService:
    def __init__(self) -> None:
        self._plans = VideoPlanRepository()
        self._segments = VideoSegmentRepository()
        self._candidates = VideoSegmentCandidateRepository()
        self._projects = ProjectPublicService()
        self._content_plans = ContentPlanPublicService()
        self._clock = SystemClock()

    # ---- plan resolution -------------------------------------------------
    def _latest_plan(self, session: Session, project_id: str) -> VideoPlan:
        plan = self._plans.latest(session, project_id)
        if plan is None:
            raise SegmentPlanMissingError("视频方案不存在")
        return plan

    def _resolve_plan(self, session: Session, *, project_id: str, plan_id: str | None) -> VideoPlan:
        self._projects.get_project(session, project_id=project_id)
        if plan_id is None:
            return self._latest_plan(session, project_id)
        plan = self._plans.get(session, plan_id)
        if plan is None or plan.project_id != project_id:
            raise SegmentPlanMissingError("视频方案不存在")
        return plan

    def _require_content_plan(self, session: Session, project_id: str, plan: VideoPlan) -> ContentPlan | None:
        if plan.mode != "product" or plan.template_id not in PRODUCT_SCENE_TEMPLATES:
            return None
        content_plan = self._content_plans.latest(session, project_id)
        if content_plan is None or content_plan.status != CONTENT_PLAN_CONFIRMED:
            raise SegmentPlanNotConfirmedError("请先确认视频分镜")
        return content_plan

    def _materialize(self, session: Session, project_id: str, plan: VideoPlan) -> list[VideoSegment]:
        content_plan = self._require_content_plan(session, project_id, plan)
        if content_plan is None:
            return []
        variant = content_plan.variants[content_plan.selected_variant_index]
        now = self._clock.now()
        segments = [
            VideoSegment(
                id=new_id("seg"), plan_id=plan.id, project_id=project_id, order_index=scene.order,
                scene_id=scene.scene_id, start_seconds=float(scene.start_seconds), end_seconds=float(scene.end_seconds),
                status=SEGMENT_PLANNED, accepted_candidate_id=None, last_error=None,
                created_at=now, updated_at=now,
            )
            for scene in sorted(variant.scenes, key=lambda item: item.order)
        ]
        self._segments.add_many(session, segments)
        session.commit()
        return self._segments.list_for_plan(session, plan.id)

    def materialize_segments(self, session: Session, *, project_id: str, plan_id: str | None = None) -> list[VideoSegment]:
        plan = self._resolve_plan(session, project_id=project_id, plan_id=plan_id)
        existing = self._segments.list_for_plan(session, plan.id)
        if existing:
            return existing
        return self._materialize(session, project_id, plan)

    # ---- candidate lifecycle --------------------------------------------
    def accept_candidate(self, session: Session, *, project_id: str, candidate_id: str) -> list[VideoSegment]:
        candidate = self._candidates.get(session, candidate_id)
        if candidate is None or candidate.project_id != project_id:
            raise SegmentNotFoundError("候选不存在")
        self._projects.get_project(session, project_id=project_id)
        segment = self._segments.get(session, candidate.segment_id)
        if segment is None:
            raise SegmentNotFoundError("视频分段不存在")
        now = self._clock.now()
        refreshed = replace(segment, status=SEGMENT_ACCEPTED, accepted_candidate_id=candidate.id, last_error=None, updated_at=now)
        self._segments.update(session, refreshed)
        self._candidates.update_status(session, candidate.id, CANDIDATE_ACCEPTED)
        self._invalidate_downstream(session, segment, now)
        session.commit()
        return self._segments.list_for_plan(session, segment.plan_id)

    def _invalidate_downstream(self, session: Session, segment: VideoSegment, now) -> None:
        for downstream in self._segments.list_for_plan(session, segment.plan_id):
            if downstream.order_index <= segment.order_index:
                continue
            previous_accepted = downstream.accepted_candidate_id
            next_status = SEGMENT_AWAITING_REVIEW if downstream.candidates else SEGMENT_PLANNED
            if previous_accepted is None and downstream.status == next_status:
                continue
            cleared = replace(downstream, status=next_status, accepted_candidate_id=None, last_error=None, updated_at=now)
            self._segments.update(session, cleared)
            if previous_accepted:
                self._candidates.update_status(session, previous_accepted, CANDIDATE_REJECTED)

    def reject_segment(self, session: Session, *, project_id: str, segment_id: str) -> list[VideoSegment]:
        segment = self._segments.get(session, segment_id)
        if segment is None or segment.project_id != project_id:
            raise SegmentNotFoundError("视频分段不存在")
        now = self._clock.now()
        if segment.accepted_candidate_id:
            self._candidates.update_status(session, segment.accepted_candidate_id, CANDIDATE_REJECTED)
        refreshed = replace(segment, status=SEGMENT_PLANNED, accepted_candidate_id=None, last_error=None, updated_at=now)
        self._segments.update(session, refreshed)
        self._invalidate_downstream(session, segment, now)
        session.commit()
        return self._segments.list_for_plan(session, segment.plan_id)
