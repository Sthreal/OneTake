from __future__ import annotations

from onetake_mcp.auth import ServiceTokenMiddleware
from onetake_mcp.client import OneTakeClient
from onetake_mcp.config import get_settings
from onetake_mcp.tools import build_mcp


settings = get_settings()
client = OneTakeClient(
    base_url=settings.api_base_url,
    timeout_seconds=settings.request_timeout_seconds,
)
mcp = build_mcp(client)
app = ServiceTokenMiddleware(mcp.streamable_http_app(), token=settings.service_token)