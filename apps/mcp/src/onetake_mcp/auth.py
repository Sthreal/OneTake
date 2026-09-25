from __future__ import annotations

import secrets

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class ServiceTokenMiddleware:
    def __init__(self, app: ASGIApp, *, token: str) -> None:
        if not token:
            raise RuntimeError("ONETAKE_MCP_TOKEN 未配置")
        self._app = app
        self._token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        authorization = headers.get(b"authorization", b"").decode("latin-1")
        expected = f"Bearer {self._token}"
        if not secrets.compare_digest(authorization, expected):
            response = JSONResponse({"detail": "Unauthorized"}, status_code=401)
            await response(scope, receive, send)
            return
        await self._app(scope, receive, send)