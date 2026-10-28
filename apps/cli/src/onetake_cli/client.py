"""CLI 的 HTTP 客户端（**只用标准库**，零新依赖）。

只做三件事：拼 URL、发请求、把非 2xx 翻成 `CliApiError`（带上服务端 message）。
**业务语义一律来自既有端点** —— CLI 里出现的每个判断（比如"能不能下载"）都必须来自服务端的字段，
不允许在命令行里自己再算一遍（否则就是第二处真相）。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_TIMEOUT_SECONDS = 30.0
USER_AGENT = "onetake-cli/1.0"

# transport(method, url, body_bytes) -> (status, body_bytes)；测试用它注入内存传输
Transport = Callable[[str, str, bytes | None], tuple[int, bytes]]


class CliApiError(Exception):
    """服务端返回非 2xx（或响应不是 JSON）。`message` 取服务端的说明，便于直接展示。"""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class ApiClient:
    def __init__(
        self, base_url: str = DEFAULT_BASE_URL, *, timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: Transport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._transport = transport or self._http_transport

    # ---- 动词 ----
    def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("GET", path, params=params)

    def post(self, path: str, *, body: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("POST", path, body=body)

    def patch(self, path: str, *, body: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("PATCH", path, body=body)

    # ---- 内部 ----
    def _request(
        self, method: str, path: str, *, params: dict[str, Any] | None = None, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        # 路径要编码：项目 id 正常是 ASCII，但一旦有人传了非 ASCII，
        # urllib 会抛 UnicodeEncodeError（真机上实测到过）——那应该是干净的 404，不是裸 traceback。
        url = f"{self.base_url}{urllib.parse.quote(path, safe='/&=%')}"
        if params:
            filtered = {key: value for key, value in params.items() if value is not None}
            if filtered:
                url = f"{url}?{urllib.parse.urlencode(filtered)}"
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        status, raw = self._transport(method, url, payload)
        if status < 200 or status >= 300:
            raise CliApiError(status, _error_message(raw, status))
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise CliApiError(status, "服务端返回的不是 JSON") from exc

    def _http_transport(self, method: str, url: str, body: bytes | None) -> tuple[int, bytes]:
        request = urllib.request.Request(
            url, data=body, method=method,
            headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except urllib.error.URLError as exc:
            raise CliApiError(0, f"连不上服务端（{url}）：{exc.reason}") from exc


def _error_message(raw: bytes, status: int) -> str:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return f"HTTP {status}"
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        code = error.get("code") or "ERROR"
        message = error.get("message") or ""
        return f"{code}：{message}" if message else str(code)
    return f"HTTP {status}"