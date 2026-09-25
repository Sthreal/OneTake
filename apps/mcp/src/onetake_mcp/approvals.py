from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

from onetake_mcp.client import OneTakeApiError


@dataclass(frozen=True)
class ApprovalRecord:
    approval_id: str
    action: str
    target: str
    summary: str
    expires_at: float


class ApprovalStore:
    def __init__(self, *, ttl_seconds: float = 600) -> None:
        self._ttl_seconds = max(30.0, float(ttl_seconds))
        self._records: dict[str, ApprovalRecord] = {}

    def create(self, *, action: str, target: str, summary: str) -> ApprovalRecord:
        self._purge()
        record = ApprovalRecord(
            approval_id=secrets.token_urlsafe(24),
            action=action,
            target=target,
            summary=summary,
            expires_at=time.time() + self._ttl_seconds,
        )
        self._records[record.approval_id] = record
        return record

    def consume(self, approval_id: str, *, action: str, target: str) -> ApprovalRecord:
        self._purge()
        record = self._records.get(approval_id)
        if record is None:
            raise OneTakeApiError('审批不存在、已使用或已过期')
        if record.action != action or record.target != target:
            raise OneTakeApiError('审批与目标操作不匹配')
        self._records.pop(approval_id, None)
        return record

    def _purge(self) -> None:
        now = time.time()
        expired = [key for key, value in self._records.items() if value.expires_at <= now]
        for key in expired:
            self._records.pop(key, None)