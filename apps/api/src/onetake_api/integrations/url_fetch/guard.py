"""SSRF 防护：判断一个 URL 能不能去抓（S13 提交 1）。

**为什么独立成模块**：SSRF 是这条链路唯一真正的安全风险，而安全校验最怕"写在业务里，测不到"。
本模块**纯函数、零 I/O**，可以穷举测试。

口径：
- 只允许 `http` / `https`
- 拒绝环回 / 私网 / 链路本地 / 保留地址（用 `ipaddress.is_global` 统一判定，天然覆盖
  `127.0.0.0/8`、`10/8`、`172.16/12`、`192.168/16`、`169.254/16`、`::1`、`fc00::/7`、`0.0.0.0`）
- 拒绝 `localhost` 一类的主机名
- 拒绝**数字化的 IP 变体**（`http://2130706433/` = 127.0.0.1、`http://0x7f000001/`）——
  它们能绕过只看点分十进制的校验
- 限制 URL 长度

**已知局限（如实写在这里）**：本函数不解析 DNS（那会引入 I/O，破坏可穷举性），所以不能防
"DNS 解析后才指向内网"的变体（DNS rebinding / `127.0.0.1.nip.io` 这类）。缓解手段是把**每一次
跳转**都过一遍本函数（`fetcher` 会做，上限 3 跳），并给 httpx 设短超时与最大体积。
彻底的做法是"解析 DNS 后校验解析结果"，属后续可另开的安全加固切片。
"""
from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from onetake_api.platform.errors import DomainError

ALLOWED_SCHEMES = frozenset({"http", "https"})
MAX_URL_LENGTH = 2048
MAX_REDIRECTS = 3

# 明确拉黑的主机名（子域一律匹配，如 a.localhost）
BLOCKED_HOSTNAMES = frozenset({"localhost", "ip6-localhost", "metadata.google.internal", "metadata"})
BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal")


class UrlNotAllowedError(DomainError):
    """目标 URL 不允许抓取（SSRF 防护）。"""

    code = "URL_NOT_ALLOWED"
    http_status = 422


def _resolve_host_kind(host: str) -> str:
    """把主机分成 `ip` / `numeric` / `name` 三类。纯字符串判定，不做 DNS。"""
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return "ip"
    # 数字/十六进制写法（2130706433 / 0x7f000001 / 0177.0.0.1）都只有这些字符，
    # 合法域名不可能长这样 → 一律当可疑的 IP 变体
    stripped = host.strip("[]")
    if stripped and all(ch in "0123456789abcdefxX:." for ch in stripped):
        return "numeric"
    return "name"


def _is_public_ip(host: str) -> bool:
    ip = ipaddress.ip_address(host)
    # `::ffff:127.0.0.1` 这类 IPv4 映射地址要按里面的 IPv4 判
    if getattr(ip, "ipv4_mapped", None) is not None:
        ip = ip.ipv4_mapped
    return ip.is_global


def validate_target_url(url: str) -> str:
    """校验并返回可抓取的 URL；不允许时抛 `UrlNotAllowedError`。

    调用方必须对**每一次跳转**都调用它（见 `fetcher.fetch_html`）。
    """
    raw = (url or "").strip()
    if not raw:
        raise UrlNotAllowedError("URL 不能为空")
    if len(raw) > MAX_URL_LENGTH:
        raise UrlNotAllowedError(f"URL 过长（超过 {MAX_URL_LENGTH} 字符）")

    parts = urlsplit(raw)
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise UrlNotAllowedError(f"只允许 http/https，收到 {parts.scheme or '(空)'}")

    host = (parts.hostname or "").strip().lower()
    if not host:
        raise UrlNotAllowedError("URL 缺少主机名")
    if host in BLOCKED_HOSTNAMES or host.endswith(BLOCKED_HOST_SUFFIXES):
        raise UrlNotAllowedError(f"不允许访问 {host}（本机/内网/元数据地址）")

    kind = _resolve_host_kind(host)
    if kind == "numeric":
        raise UrlNotAllowedError(f"不允许使用数字形式的 IP（{host}），这类写法能绕过常规校验")
    if kind == "ip" and not _is_public_ip(host):
        raise UrlNotAllowedError(f"不允许访问内网/保留地址（{host}）")

    return raw


def redirect_budget_ok(hop: int) -> bool:
    """第 `hop` 次跳转是否还在预算内（0 基：首次请求算第 0 跳）。"""
    return hop < MAX_REDIRECTS