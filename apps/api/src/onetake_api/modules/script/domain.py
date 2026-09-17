from dataclasses import dataclass
from datetime import datetime

STATUS_QUEUED = "queued"
STATUS_GENERATING = "generating"
STATUS_READY = "ready"
STATUS_CONFIRMED = "confirmed"
STATUS_FAILED = "failed"

ACTIVE_STATUSES = {STATUS_QUEUED, STATUS_GENERATING}
EDITABLE_STATUSES = {STATUS_READY, STATUS_CONFIRMED}


@dataclass(frozen=True)
class ScriptInput:
    product_name: str
    product_note: str | None
    pain_point: str
    selling_points: tuple[str, ...]
    usage_scenario: str
    offer: str | None


@dataclass(frozen=True)
class ScriptDraft:
    hook: str
    pain_point: str
    selling_points: tuple[str, ...]
    usage_scenario: str
    cta: str


@dataclass(frozen=True)
class ScriptVersion:
    id: str
    project_id: str
    version_number: int
    status: str
    provider: str
    model: str
    source_object_key: str
    facts: dict
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
