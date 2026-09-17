from dataclasses import dataclass
from datetime import datetime

RUN_QUEUED = "queued"
RUN_RUNNING = "running"
RUN_READY = "ready"
RUN_CONFIRMED = "confirmed"
RUN_FAILED = "failed"


@dataclass(frozen=True)
class RecognitionRun:
    id: str
    project_id: str
    status: str
    input_hash: str
    selected_asset_id: str | None
    selected_candidate_id: str | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True)
class RecognitionCandidate:
    id: str
    run_id: str
    asset_id: str
    label: str
    confidence: float
    reason: str
    created_at: datetime


@dataclass(frozen=True)
class CandidateDraft:
    asset_id: str
    label: str
    confidence: float
    reason: str
