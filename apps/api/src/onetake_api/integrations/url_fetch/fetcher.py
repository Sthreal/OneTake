"""受控 HTTP 抓取（S13 提交 2）。

两条硬原则：
1. **每一次跳转都过 guard** —— 用 `follow_redirects=False`，自己在循环里跟跳转，逐跳校验。
   "首跳合法、二跳内网"是 SSRF 的经典绕过路径，交给 httpx 自动跟随就等于放弃了防护。
2. **一切都有上限** —— 超时、响应体积（流式读取，超限即断开，不会先把几百 MB 读进内存）、
   MIME 类型（只接受 HTML / 常见图片格式）。

`client` 可注入：测试用 `httpx.MockTransport` 就能在**零出网**的前提下覆盖全部分支。
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from onetake_api.integrations.url_fetch.guard import (
    MAX_REDIRECTS,
    UrlNotAllowedError,
    validate_target_url,
)
from onetake_api.platform.errors import DomainError

REQUEST_TIMEOUT_SECONDS = 10.0
MAX_HTML_BYTES = 2 * 1024 * 1024
MAX_IMAGE_BYTES = 6 * 1024 * 1024
ALLOWED_HTML_TYPES = ("text/html", "application/xhtml+xml")
ALLOWED_IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp")
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
USER_AGENT = "OneTakeBot/0.1 (+product-url-import)"


class UrlFetchError(DomainError):
    """抓取失败（网络/超时/体积/类型/跳转超限）。由上层降级为"手动上传"。"""

    code = "URL_FETCH_FAILED"
    http_status = 502
    retryable = True


@dataclass(frozen=True)
class FetchedPage:
    url: str  # 最终 URL（可能经过跳转），后续相对链接以它为基准
    html: str
    content_type: str


@dataclass(frozen=True)
class FetchedBinary:
    url: str
    content: bytes
    content_type: str


def build_client() -> httpx.Client:
    """默认客户端：短超时 + 自己的 UA（有些站点对默认 UA 返回 403）。"""
    return httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT})


def _get_with_guard(
    client: httpx.Client, url: str, *, max_bytes: int
) -> tuple[str, int, dict[str, str], bytes]:
    """逐跳带 guard 的 GET；流式读取并在超过 `max_bytes` 时立即失败。

    返回 (最终 URL, 状态码, 响应头, body)。
    """
    current = validate_target_url(url)
    for hop in range(MAX_REDIRECTS + 1):
        with client.stream("GET", current, follow_redirects=False) as response:
            if response.status_code in REDIRECT_STATUSES:
                location = response.headers.get("location")
                if not location:
                    raise UrlFetchError("重定向响应缺少 Location")
                if hop >= MAX_REDIRECTS:
                    raise UrlFetchError(f"跳转次数超过上限（{MAX_REDIRECTS} 次）")
                # 关键：跳转目标同样要过 guard（防"二跳内网"）
                current = validate_target_url(urljoin(current, location))
                continue
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise UrlFetchError(f"响应体积超过上限（{max_bytes // 1024} KB）")
            return current, response.status_code, dict(response.headers), bytes(body)
    raise UrlFetchError(f"跳转次数超过上限（{MAX_REDIRECTS} 次）")


def _content_type(headers: dict[str, str]) -> str:
    return (headers.get("content-type") or "").split(";")[0].strip().lower()


def _run(url: str, client: httpx.Client | None, call):
    owns = client is None
    active = client or build_client()
    try:
        return call(active)
    except UrlNotAllowedError:
        raise  # SSRF 拒绝要原样上抛（上层据此返回 4xx，而不是当成"抓取失败"）
    except httpx.HTTPError as exc:
        raise UrlFetchError("抓取失败（网络错误或超时）") from exc
    finally:
        if owns:
            active.close()


def fetch_html(url: str, *, client: httpx.Client | None = None) -> FetchedPage:
    def call(active: httpx.Client) -> FetchedPage:
        final_url, status, headers, body = _get_with_guard(active, url, max_bytes=MAX_HTML_BYTES)
        if status >= 400:
            raise UrlFetchError(f"目标返回 {status}")
        content_type = _content_type(headers)
        if content_type and content_type not in ALLOWED_HTML_TYPES:
            raise UrlFetchError(f"目标不是 HTML（{content_type}）")
        return FetchedPage(url=final_url, html=body.decode("utf-8", errors="replace"), content_type=content_type or "text/html")

    return _run(url, client, call)


def fetch_image(url: str, *, client: httpx.Client | None = None) -> FetchedBinary:
    def call(active: httpx.Client) -> FetchedBinary:
        final_url, status, headers, body = _get_with_guard(active, url, max_bytes=MAX_IMAGE_BYTES)
        if status >= 400:
            raise UrlFetchError(f"图片返回 {status}")
        content_type = _content_type(headers)
        if content_type not in ALLOWED_IMAGE_TYPES:
            raise UrlFetchError(f"不支持的图片类型（{content_type or '未知'}）")
        if not body:
            raise UrlFetchError("图片内容为空")
        return FetchedBinary(url=final_url, content=body, content_type=content_type)

    return _run(url, client, call)