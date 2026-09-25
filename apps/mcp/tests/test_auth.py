import asyncio

import httpx
import pytest
from starlette.responses import JSONResponse

from onetake_mcp.auth import ServiceTokenMiddleware


async def _ok_app(scope, receive, send):
    response = JSONResponse({"ok": True})
    await response(scope, receive, send)


async def _call(token: str | None):
    app = ServiceTokenMiddleware(_ok_app, token="expected-token")
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/mcp", headers=headers)


def test_auth_rejects_missing_token() -> None:
    response = asyncio.run(_call(None))
    assert response.status_code == 401


def test_auth_accepts_expected_token() -> None:
    response = asyncio.run(_call("expected-token"))
    assert response.status_code == 200


def test_auth_requires_configured_token() -> None:
    with pytest.raises(RuntimeError, match="ONETAKE_MCP_TOKEN"):
        ServiceTokenMiddleware(_ok_app, token="")