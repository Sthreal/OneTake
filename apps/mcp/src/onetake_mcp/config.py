from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def _env_hosts(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, '')
    return tuple(item.strip().lower() for item in raw.split(',') if item.strip())


@dataclass(frozen=True)
class Settings:
    api_base_url: str
    service_token: str
    approval_token: str
    request_timeout_seconds: float
    write_enabled: bool
    paid_enabled: bool
    asset_hosts: tuple[str, ...]


def get_settings() -> Settings:
    return Settings(
        api_base_url=os.getenv('ONETAKE_API_BASE_URL', 'http://api:8000').rstrip('/'),
        service_token=os.getenv('ONETAKE_MCP_TOKEN', ''),
        approval_token=os.getenv('ONETAKE_MCP_APPROVAL_TOKEN', ''),
        request_timeout_seconds=float(os.getenv('ONETAKE_MCP_REQUEST_TIMEOUT_SECONDS', '10')),
        write_enabled=_env_bool('ONETAKE_MCP_WRITE_ENABLED', False),
        paid_enabled=_env_bool('ONETAKE_MCP_PAID_ENABLED', False),
        asset_hosts=_env_hosts('ONETAKE_MCP_ASSET_HOSTS'),
    )