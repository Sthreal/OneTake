from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx


class OneTakeApiError(RuntimeError):
    pass


class OneTakeClient:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float = 10,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = max(1.0, float(timeout_seconds))
        self._client = client

    async def get_provider_status(self) -> Any:
        return await self._get("/api/v1/providers/status")

    async def list_projects(self, limit: int = 20) -> Any:
        if limit < 1 or limit > 50:
            raise ValueError("limit 必须在 1 到 50 之间")
        return await self._get("/api/v1/projects", params={"limit": limit})

    async def get_project(self, project_id: str) -> Any:
        return await self._get(f"/api/v1/projects/{quote(project_id, safe='')}")

    async def get_pipeline(self, project_id: str) -> Any:
        return await self._get(f"/api/v1/projects/{quote(project_id, safe='')}/pipeline")

    async def get_video(self, project_id: str) -> Any:
        return await self._get(f"/api/v1/projects/{quote(project_id, safe='')}/video")

    async def estimate_video_cost(self, project_id: str, plan_id: str) -> Any:
        return await self._get(
            f"/api/v1/projects/{quote(project_id, safe='')}/video-plan/{quote(plan_id, safe='')}/estimate"
        )

    async def _get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        try:
            if self._client is not None:
                response = await self._client.get(
                    f"{self._base_url}{path}",
                    params=params,
                    timeout=self._timeout_seconds,
                )
            else:
                async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                    response = await client.get(f"{self._base_url}{path}", params=params)
        except httpx.HTTPError as exc:
            raise OneTakeApiError("One Take API 不可用") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise OneTakeApiError(f"One Take API 返回非 JSON：HTTP {response.status_code}") from exc
        if response.status_code < 200 or response.status_code >= 300:
            detail = payload.get("detail") if isinstance(payload, dict) else None
            raise OneTakeApiError(f"One Take API 请求失败：{detail or response.status_code}")
        return payload.get("data", payload) if isinstance(payload, dict) else payload