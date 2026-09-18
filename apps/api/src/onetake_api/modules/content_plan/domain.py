from dataclasses import dataclass
from datetime import datetime

STATUS_READY = "ready"
STATUS_CONFIRMED = "confirmed"
STATUS_FAILED = "failed"


@dataclass(frozen=True)
class ContentScene:
    scene_id: str
    order: int
    purpose: str
    script_excerpt: str
    start_seconds: float
    end_seconds: float
    shot_type: str
    prompt: str
    overlay_product: bool
    product_position: str
    background_style: str
    template_id: str
    subtitle_segment_ids: list[int]
    qa_rules: list[str]


@dataclass(frozen=True)
class ContentVariant:
    variant_id: str
    name: str
    style: str
    scenes: list[ContentScene]


@dataclass(frozen=True)
class ContentPlan:
    id: str
    project_id: str
    script_version_id: str
    subtitle_version_id: str
    status: str
    provider: str
    model: str
    variants: list[ContentVariant]
    selected_variant_index: int
    total_duration_seconds: float
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None
