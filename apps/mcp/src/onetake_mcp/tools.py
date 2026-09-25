from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from onetake_mcp.client import OneTakeClient


def build_mcp(client: OneTakeClient) -> FastMCP:
    mcp = FastMCP(
        "One Take",
        instructions="Read-only tools for One Take projects and video pipeline status.",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=[
                'localhost:8010',
                '127.0.0.1:8010',
                'mcp:8010',
                'host.docker.internal:8010',
            ],
            allowed_origins=[
                'http://localhost:8010',
                'http://127.0.0.1:8010',
                'http://mcp:8010',
                'http://host.docker.internal:8010',
            ],
        ),
    )

    @mcp.tool()
    async def onetake_get_provider_status() -> Any:
        """Read configured and effective One Take provider status."""
        return await client.get_provider_status()

    @mcp.tool()
    async def onetake_list_projects(limit: int = 20) -> Any:
        """List recent One Take projects."""
        return await client.list_projects(limit=limit)

    @mcp.tool()
    async def onetake_get_project(project_id: str) -> Any:
        """Read one One Take project by project ID."""
        return await client.get_project(project_id)

    @mcp.tool()
    async def onetake_get_pipeline(project_id: str) -> Any:
        """Read the current One Take pipeline state for a project."""
        return await client.get_pipeline(project_id)

    @mcp.tool()
    async def onetake_get_video(project_id: str) -> Any:
        """Read the current video plan and output state for a project."""
        return await client.get_video(project_id)

    @mcp.tool()
    async def onetake_estimate_video_cost(project_id: str, plan_id: str) -> Any:
        """Estimate the cost of generating the specified video plan."""
        return await client.estimate_video_cost(project_id, plan_id)

    return mcp