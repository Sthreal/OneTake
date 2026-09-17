from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, JSON, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from onetake_api.modules.outbox.domain.event import OutboxEvent
from onetake_api.platform.database import Base


class OutboxEventModel(Base):
    __tablename__ = "outbox_events"
    __table_args__ = {"schema": "outbox"}

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    event_name: Mapped[str] = mapped_column(String(100), nullable=False)
    event_version: Mapped[int] = mapped_column(Integer, nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(50), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SqlAlchemyOutboxRepository:
    def add(self, session: Session, event: OutboxEvent) -> None:
        session.add(
            OutboxEventModel(
                id=event.id,
                event_name=event.event_name,
                event_version=event.event_version,
                aggregate_type=event.aggregate_type,
                aggregate_id=event.aggregate_id,
                payload=event.payload,
                status=event.status,
                attempts=event.attempts,
                available_at=event.available_at,
                created_at=event.created_at,
                published_at=event.published_at,
            )
        )