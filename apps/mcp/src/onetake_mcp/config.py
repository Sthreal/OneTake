from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    api_base_url: str
    service_token: str
    request_timeout_seconds: float


def get_settings() -> Settings:
    return Settings(
        api_base_url=os.getenv("ONETAKE_API_BASE_URL", "http://api:8000").rstrip("/"),
        service_token=os.getenv("ONETAKE_MCP_TOKEN", ""),
        request_timeout_seconds=float(os.getenv("ONETAKE_MCP_REQUEST_TIMEOUT_SECONDS", "10")),
    )