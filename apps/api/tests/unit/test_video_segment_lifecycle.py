from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy.orm import Session

from onetake_api.modules.video_plan.segment_domain import (
    CANDIDATE_ACCEPTED,
    CANDIDATE_REJECTED,
    SEGMENT_ACCEPTED,
    SEGMENT_AWAITING_REVIEW,
    SEGMENT_PLANNED,
    VideoSegment,
    VideoSegmentCandidate,
)
from onetake_api.modules.video_plan.segment_repository import (
    VideoSegmentCandidateRepository,
    VideoSegmentRepository,
)
from onetake_api.modules.video_plan.segment_service import (
    SegmentNotFoundError,
    VideoSegmentApplicationService,
)
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.platform.clock import SystemClock


def _seed_segment(session: Session, *, project_id: str, plan_id: str, order_index: int, candidate_count: int = 0) -> VideoSegment:
    now = SystemClock().now()
    segment = VideoSegment(
        id=f"seg_{plan_id}_{order_index}", plan_id=plan_id, project_id=project_id, order_index=order_index,
        scene_id=f"scene_{order_index}", start_seconds=float(order_index * 5), end_seconds=float(order_index * 5 + 5),
        status=SEGMENT_PLANNED, accepted_candidate_id=None, last_error=None, created_at=now, updated_at=now,
    )
    VideoSegmentRepository().add_many(session, [segment])
    for index in range(candidate_count):
        VideoSegmentCandidateRepository().add(session, VideoSegmentCandidate(
            id=f"cand_{plan_id}_{order_index}_{index}", segment_id=segment.id, plan_id=plan_id, project_id=project_id,
            order_index=index + 1, status="ready", provider="mock", anchor_source="scene_keyframe",
            created_at=now, video_object_key=f"projects/{project_id}/seg/{order_index}/{index}.mp4",
        ))
    session.flush()
    return VideoSegmentRepository().get(session, segment.id)  # type: ignore[return-value]


def test_segment_duration_is_end_minus_start() -> None:
    now = SystemClock().now()
    segment = VideoSegment(
        id="seg_x", plan_id="vid_x", project_id="prj_x", order_index=0, scene_id="scene_0",
        start_seconds=2.0, end_seconds=7.5, status=SEGMENT_PLANNED, created_at=now, updated_at=now,
    )
    assert segment.duration_seconds == 5.5


def test_candidate_repository_next_order_index(db_session: Session) -> None:
    segment = _seed_segment(db_session, project_id="prj_a", plan_id="vid_a", order_index=0, candidate_count=2)
    assert VideoSegmentCandidateRepository().next_order_index(db_session, segment.id) == 3


def test_accept_candidate_invalidates_downstream_only(db_session: Session) -> None:
    service = VideoSegmentApplicationService()
    project_id = ProjectPublicService().create_project(db_session, product_name="分段", product_note=None).id
    first = _seed_segment(db_session, project_id=project_id, plan_id="vid_b", order_index=0, candidate_count=1)
    second = _seed_segment(db_session, project_id=project_id, plan_id="vid_b", order_index=1, candidate_count=1)
    third = _seed_segment(db_session, project_id=project_id, plan_id="vid_b", order_index=2, candidate_count=1)
    # 先接受第 2、3 段，制造下游已接受的状态
    service.accept_candidate(db_session, project_id=project_id, candidate_id=second.candidates[0].id)
    service.accept_candidate(db_session, project_id=project_id, candidate_id=third.candidates[0].id)

    segments = service.accept_candidate(db_session, project_id=project_id, candidate_id=first.candidates[0].id)
    by_order = {seg.order_index: seg for seg in segments}

    assert by_order[0].status == SEGMENT_ACCEPTED
    assert by_order[0].accepted_candidate_id == first.candidates[0].id
    assert by_order[1].accepted_candidate_id is None
    assert by_order[2].accepted_candidate_id is None
    assert by_order[1].status == SEGMENT_AWAITING_REVIEW
    assert by_order[2].status == SEGMENT_AWAITING_REVIEW
    assert VideoSegmentCandidateRepository().get(db_session, second.candidates[0].id).status == CANDIDATE_REJECTED


def test_reject_segment_clears_accepted_and_downstream(db_session: Session) -> None:
    service = VideoSegmentApplicationService()
    project_id = ProjectPublicService().create_project(db_session, product_name="分段2", product_note=None).id
    first = _seed_segment(db_session, project_id=project_id, plan_id="vid_c", order_index=0, candidate_count=1)
    second = _seed_segment(db_session, project_id=project_id, plan_id="vid_c", order_index=1, candidate_count=1)
    service.accept_candidate(db_session, project_id=project_id, candidate_id=first.candidates[0].id)
    service.accept_candidate(db_session, project_id=project_id, candidate_id=second.candidates[0].id)

    segments = service.reject_segment(db_session, project_id=project_id, segment_id=second.id)
    by_order = {seg.order_index: seg for seg in segments}
    assert by_order[1].status == SEGMENT_PLANNED
    assert by_order[1].accepted_candidate_id is None
    assert by_order[0].status == SEGMENT_ACCEPTED


def test_accept_unknown_candidate_raises(db_session: Session) -> None:
    service = VideoSegmentApplicationService()
    with pytest.raises(SegmentNotFoundError):
        service.accept_candidate(db_session, project_id="prj_missing", candidate_id="cand_missing")
