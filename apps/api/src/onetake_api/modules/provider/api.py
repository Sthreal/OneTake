from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from onetake_api.modules.provider.service import get_provider_statuses
from onetake_api.platform.request_context import get_request_id

router = APIRouter(prefix="/api/v1/providers", tags=["providers"])


class ProviderStatusData(BaseModel):
    capability: str
    configured_mode: str
    effective_mode: str
    configured_provider: str
    effective_provider: str
    configured: bool
    ready: bool
    reason: str | None


class ProviderStatusResponse(BaseModel):
    data: list[ProviderStatusData]
    request_id: str


@router.get("/status", response_model=ProviderStatusResponse)
def provider_status() -> ProviderStatusResponse:
    return ProviderStatusResponse(
        data=[
            ProviderStatusData(
                capability=item.capability,
                configured_mode=item.configured_mode,
                effective_mode=item.effective_mode,
                configured_provider=item.configured_provider,
                effective_provider=item.effective_provider,
                configured=item.configured,
                ready=item.ready,
                reason=item.reason,
            )
            for item in get_provider_statuses()
        ],
        request_id=get_request_id(),
    )
