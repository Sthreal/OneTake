from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class OutboxEvent:
    id: str
    event_name: str
    event_version: int
    aggregate_type: str
    aggregate_id: str
    payload: dict[str, Any]
    status: str
    attempts: int
    available_at: datetime
    created_at: datetime
    published_at: datetime | None = None