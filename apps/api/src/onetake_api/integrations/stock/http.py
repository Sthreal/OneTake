"""素材平台的 HTTP 细节（批次 4a）：统一 UA / 超时 / 跟随重定向 / 传输层重试。

三件事都在这里，是因为它们是**实测踩出来的**：
1. **必须带可识别的 User-Agent**：Wikimedia 的 robot policy 会对"没有联系方式的 UA"或高频请求返回 403；
   本机实测一次密集请求后连正常 UA 也被 403，过一会儿恢复 —— 所以 403 一律当"可重试的源故障"抛出去，
   由调用方回退原生成路径（绝不让素材检索把成片搞失败）。
2. **必须跟随重定向**：Openverse 把无尾斜杠路径 301 到带尾斜杠形式，httpx 默认不跟随。
3. **传输层要重试一次**：本机经过本地代理时偶发 `Server disconnected`（同一 UA 下 urllib 正常），
   重试一次即可恢复 —— 只重试**传输层**错误，不重试 4xx（那是语义错误，重试没用）。
"""
from __future__ import annotations

import time
from typing import Any

import httpx

TIMEOUT_SECONDS = 15.0
USER_AGENT = "OneTakeBot/1.0 (+https://github.com/xixihhhh/clipforge; contact: configure STOCK_USER_AGENT)"
TRANSPORT_RETRIES = 2
RETRY_BACKOFF_SECONDS = 0.4


def build_client(*, user_agent: str | None = None, timeout: float | None = None) -> httpx.Client:
    return httpx.Client(
        timeout=TIMEOUT_SECONDS if timeout is None else timeout,
        headers={"User-Agent": user_agent or USER_AGENT},
        follow_redirects=True,
    )


def get_bytes(
    *, url: str, client: httpx.Client | None, max_bytes: int, sleep=time.sleep
) -> bytes:
    """下载二进制素材（图片/音视频），带**体积上限**：超限直接拒绝，不把几十 MB 的东西拖进来。

    先看 `Content-Length`（能挡掉大多数超大文件），再在真正读完后复核一次（有的站点不报长度）。
    """
    owns_client = client is None
    http = client or build_client()
    try:
        for attempt in range(TRANSPORT_RETRIES + 1):
            try:
                with http.stream("GET", url) as response:
                    response.raise_for_status()
                    declared = response.headers.get("Content-Length")
                    if declared and declared.isdigit() and int(declared) > max_bytes:
                        raise httpx.HTTPError(f"素材体积 {declared} 字节超过上限 {max_bytes}")
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise httpx.HTTPError(f"素材体积超过上限 {max_bytes} 字节")
                        chunks.append(chunk)
                return b"".join(chunks)
            except httpx.TransportError as exc:
                if attempt >= TRANSPORT_RETRIES:
                    raise
                sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
        raise RuntimeError("素材下载未执行")
    finally:
        if owns_client:
            http.close()


def get_json(
    *, url: str, params: dict[str, Any], client: httpx.Client | None,
    sleep=time.sleep,
) -> dict[str, Any]:
    """GET 并解析 JSON；失败抛 `httpx.HTTPError` / `ValueError`（**由调用方翻成领域错误**）。

    `client` 为 None 时自建（用完即关）；测试可注入 `httpx.MockTransport` 的客户端。
    """
    owns_client = client is None
    http = client or build_client()
    try:
        last_error: Exception | None = None
        for attempt in range(TRANSPORT_RETRIES + 1):
            try:
                response = http.get(url, params=params)
                response.raise_for_status()
                body = response.json()
            except httpx.TransportError as exc:
                last_error = exc
                if attempt >= TRANSPORT_RETRIES:
                    raise
                sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
                continue
            if not isinstance(body, dict):
                raise ValueError("素材平台返回的不是 JSON 对象")
            return body
        raise last_error if last_error else RuntimeError("素材请求未执行")
    finally:
        if owns_client:
            http.close()