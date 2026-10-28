"""S13 提交 1 单测：SSRF 防护（纯函数，零 I/O → 可穷举）。

覆盖档案 S13 验收 2 与 5：内网/环回/云元数据地址全部拒绝；重定向目标同样要过 guard。
"""
from __future__ import annotations

import pytest

from onetake_api.integrations.url_fetch.guard import (
    ALLOWED_SCHEMES,
    MAX_REDIRECTS,
    MAX_URL_LENGTH,
    UrlNotAllowedError,
    redirect_budget_ok,
    validate_target_url,
)

# 合法目标：真实存在的公网主机（含带路径/查询串、带端口、IPv4 字面量）
ALLOWED = (
    "https://example.com/product/1234",
    "http://8.8.8.8/x",
    "https://shop.example.co.uk/p?sku=1&ref=abc",
    "https://example.com:8443/p",
)

# 危险目标：逐条标明它想绕过什么
BLOCKED = (
    ("http://localhost:8000/api/v1/projects", "本机"),
    ("https://localhost/", "本机 https"),
    ("http://a.localhost/", "本机子域"),
    ("http://127.0.0.1/", "环回"),
    ("http://127.1.2.3/", "环回 127/8"),
    ("http://10.0.0.1/", "私网 10/8"),
    ("http://172.16.0.1/", "私网 172.16/12"),
    ("http://192.168.1.1/", "私网 192.168/16"),
    ("http://169.254.169.254/latest/meta-data/", "云元数据"),
    ("http://0.0.0.0/", "未指定地址"),
    ("http://[::1]/", "IPv6 环回"),
    ("http://[fd00::1]/", "IPv6 唯一本地"),
    ("http://metadata.google.internal/computeMetadata/v1/", "GCP 元数据主机名"),
    ("http://2130706433/", "十进制 IP（=127.0.0.1）"),
    ("http://0x7f000001/", "十六进制 IP（=127.0.0.1）"),
    ("http://user:pw@127.0.0.1/", "userinfo 伪装"),
    ("ftp://example.com/", "非 http(s) 协议"),
    ("file:///etc/passwd", "本地文件协议"),
    ("javascript:alert(1)", "伪协议"),
    ("", "空串"),
    ("not-a-url", "缺少主机名"),
    ("https://" + "a" * (MAX_URL_LENGTH + 10) + ".com/", "超长 URL"),
)


@pytest.mark.parametrize("url", ALLOWED)
def test_public_urls_are_allowed(url: str) -> None:
    assert validate_target_url(url) == url


@pytest.mark.parametrize("url,reason", BLOCKED)
def test_dangerous_urls_are_rejected(url: str, reason: str) -> None:
    """每一条都带"它想绕过什么"的说明，失败时能直接看出是哪类绕过漏了。"""
    try:
        validate_target_url(url)
    except UrlNotAllowedError as exc:
        assert exc.message, f"{url}（{reason}）被拒但没给原因"
        return
    raise AssertionError(f"{url}（{reason}）竟然被放行 —— 这是一处 SSRF 绕过")


def test_blocked_url_reports_its_own_reason() -> None:
    """拒绝信息要能说清"为什么"（否则用户与排障者都得猜）。"""
    with pytest.raises(UrlNotAllowedError) as excinfo:
        validate_target_url("http://169.254.169.254/latest/meta-data/")
    assert excinfo.value.code == "URL_NOT_ALLOWED"
    assert excinfo.value.http_status == 422
    assert "169.254.169.254" in excinfo.value.message


def test_url_is_trimmed_before_use() -> None:
    assert validate_target_url("  https://example.com/p  ") == "https://example.com/p"


def test_redirect_budget_caps_hops() -> None:
    """验收 5 的配套：跳转次数有上限，避免"跳到内网"无限追下去。"""
    assert MAX_REDIRECTS == 3
    assert redirect_budget_ok(0) and redirect_budget_ok(MAX_REDIRECTS - 1)
    assert not redirect_budget_ok(MAX_REDIRECTS)


def test_only_http_schemes_are_allowed() -> None:
    assert ALLOWED_SCHEMES == {"http", "https"}