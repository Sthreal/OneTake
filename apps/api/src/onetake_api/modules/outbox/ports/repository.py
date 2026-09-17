from typing import Protocol

from sqlalchemy.orm import Session

from onetake_api.modules.outbox.domain.event import OutboxEvent


class OutboxRepository(Protocol):
    def add(self, session: Session, event: OutboxEvent) -> None: ...