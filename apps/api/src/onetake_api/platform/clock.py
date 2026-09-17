from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def plus_hours(self, hours: int) -> datetime:
        return self.now() + timedelta(hours=hours)