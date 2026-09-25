import asyncio

import httpx
import pytest
from starlette.responses import JSONResponse

from onetake_mcp.auth import ServiceTokenMiddleware


async def _ok_app(scope, receive, send):
    response = JSONResponse({'ok': True})
    await response(scope, receive, send)


async def _call(path: str, token: str | None):
    app = ServiceTokenMiddleware(
        _ok_app,
        token='mcp-token',
        approval_token='approval-token',
    )
    headers = {'Authorization': f'Bearer {token}'} if token is not None else {}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
        return await client.get(path, headers=headers)


def test_mcp_requires_mcp_token() -> None:
    assert asyncio.run(_call('/mcp', 'approval-token')).status_code == 401
    assert asyncio.run(_call('/mcp', 'mcp-token')).status_code == 200


def test_internal_approval_requires_distinct_token() -> None:
    assert asyncio.run(_call('/internal/approvals', 'mcp-token')).status_code == 401
    assert asyncio.run(_call('/internal/approvals', 'approval-token')).status_code == 200


def test_auth_requires_configured_token() -> None:
    with pytest.raises(RuntimeError, match='ONETAKE_MCP_TOKEN'):
        ServiceTokenMiddleware(_ok_app, token='')