from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

SEGMENT_PLANNED = "planned"
SEGMENT_GENERATING = "generating"
SEGMENT_AWAITING_REVIEW = "awaiting_review"
SEGMENT_ACCEPTED = "accepted"
SEGMENT_FAILED = "failed"
SEGMENT_STATUSES = frozenset({SEGMENT_PLANNED, SEGMENT_GENERATING, SEGMENT_AWAITING_REVIEW, SEGMENT_ACCEPTED, SEGMENT_FAILED})

CANDIDATE_READY = "ready"
CANDIDATE_ACCEPTED = "accepted"
CANDIDATE_REJECTED = "rejected"
CANDIDATE_FAILED = "failed"


@dataclass(frozen=True)
class VideoSegmentCandidate:
    id: str
    segment_id: str
    plan_id: str
    project_id: str
    order_index: int
    status: str
    provider: str
    anchor_source: str
    created_at: datetime
    video_object_key: str | None = None
    tail_frame_object_key: str | None = None
    head_frame_object_key: str | None = None
    anchor_candidate_id: str | None = None
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    fps: int | None = None
    seed: int | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class VideoSegment:
    id: str
    plan_id: str
    project_id: str
    order_index: int
    scene_id: str
    start_seconds: float
    end_seconds: float
    status: str
    created_at: datetime
    updated_at: datetime
    accepted_candidate_id: str | None = None
    last_error: str | None = None
    candidates: list[VideoSegmentCandidate] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        return round(max(0.0, self.end_seconds - self.start_seconds), 3)
