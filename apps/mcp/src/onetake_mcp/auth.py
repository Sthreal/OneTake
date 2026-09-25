from __future__ import annotations

import secrets

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class ServiceTokenMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        token: str,
        approval_token: str = '',
    ) -> None:
        if not token:
            raise RuntimeError('ONETAKE_MCP_TOKEN 未配置')
        self._app = app
        self._token = token
        self._approval_token = approval_token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get('type') != 'http':
            await self._app(scope, receive, send)
            return
        path = str(scope.get('path') or '')
        headers = {key.lower(): value for key, value in scope.get('headers', [])}
        authorization = headers.get(b'authorization', b'').decode('latin-1')
        if path.startswith('/internal/approvals'):
            expected_token = self._approval_token
        else:
            expected_token = self._token
        expected = f'Bearer {expected_token}' if expected_token else ''
        if not expected or not secrets.compare_digest(authorization, expected):
            response = JSONResponse({'detail': 'Unauthorized'}, status_code=401)
            await response(scope, receive, send)
            return
        await self._app(scope, receive, send)