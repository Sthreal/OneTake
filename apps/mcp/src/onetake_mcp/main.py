from __future__ import annotations

from onetake_mcp.approvals import ApprovalStore
from onetake_mcp.auth import ServiceTokenMiddleware
from onetake_mcp.client import OneTakeClient
from onetake_mcp.config import get_settings
from onetake_mcp.tools import build_mcp


settings = get_settings()
client = OneTakeClient(
    base_url=settings.api_base_url,
    timeout_seconds=settings.request_timeout_seconds,
)
approvals = ApprovalStore()
mcp = build_mcp(client, settings=settings, approvals=approvals)
app = ServiceTokenMiddleware(
    mcp.streamable_http_app(),
    token=settings.service_token,
    approval_token=settings.approval_token,
)