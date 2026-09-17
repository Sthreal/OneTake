from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from onetake_api.modules.outbox.application.service import OutboxApplicationService


class OutboxPublicService:
    def enqueue(
        self,
        session: Session,
        *,
        event_name: str,
        aggregate_type: str,
        aggregate_id: str,
        payload: dict[str, Any],
        occurred_at: datetime,
    ) -> str:
        return OutboxApplicationService().enqueue(
            session,
            event_name=event_name,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=payload,
            occurred_at=occurred_at,
        )