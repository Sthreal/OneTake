from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from onetake_api.modules.outbox.adapters.sqlalchemy_repository import SqlAlchemyOutboxRepository
from onetake_api.modules.outbox.domain.event import OutboxEvent
from onetake_api.platform.ids import new_id


class OutboxApplicationService:
    def enqueue(
        self,
        session: Session,
        *,
        event_name: str,
        aggregate_type: str,
        aggregate_id: str,
        payload: dict[str, Any],
        occurred_at: datetime,
        event_version: int = 1,
    ) -> str:
        event = OutboxEvent(
            id=new_id("evt"),
            event_name=event_name,
            event_version=event_version,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=payload,
            status="pending",
            attempts=0,
            available_at=occurred_at,
            created_at=occurred_at,
            published_at=None,
        )
        SqlAlchemyOutboxRepository().add(session, event)
        return event.id