"""关键帧候选领域对象（Phase 1）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

KEYFRAME_READY = "ready"
KEYFRAME_ACCEPTED = "accepted"
KEYFRAME_REJECTED = "rejected"
KEYFRAME_FAILED = "failed"
KEYFRAME_STATUSES = frozenset({KEYFRAME_READY, KEYFRAME_ACCEPTED, KEYFRAME_REJECTED, KEYFRAME_FAILED})


@dataclass(frozen=True)
class VideoKeyframeCandidate:
    id: str
    project_id: str
    content_plan_id: str
    scene_id: str
    order_index: int
    mode: str
    status: str
    provider: str
    created_at: datetime
    seed: int | None = None
    image_object_key: str | None = None
    width: int | None = None
    height: int | None = None
    product_match: float | None = None
    text_intact: bool | None = None
    issues: list[str] = field(default_factory=list)
    fallback: str | None = None
    error_code: str | None = None