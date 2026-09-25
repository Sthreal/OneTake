import asyncio

from onetake_mcp.tools import build_mcp


class FakeClient:
    async def get_provider_status(self):
        return [{"capability": "avatar_video"}]

    async def list_projects(self, limit=20):
        return []

    async def get_project(self, project_id):
        return {"project_id": project_id}

    async def get_pipeline(self, project_id):
        return {"project_id": project_id}

    async def get_video(self, project_id):
        return {"project_id": project_id}

    async def estimate_video_cost(self, project_id, plan_id):
        return {"project_id": project_id, "plan_id": plan_id}


def test_mcp_exposes_read_only_tool_contract() -> None:
    async def run():
        mcp = build_mcp(FakeClient())
        tools = await mcp.list_tools()
        return [tool.name for tool in tools]

    assert asyncio.run(run()) == [
        "onetake_get_provider_status",
        "onetake_list_projects",
        "onetake_get_project",
        "onetake_get_pipeline",
        "onetake_get_video",
        "onetake_estimate_video_cost",
    ]


def test_mcp_calls_provider_status_tool() -> None:
    async def run():
        mcp = build_mcp(FakeClient())
        result = await mcp.call_tool("onetake_get_provider_status", {})
        return result

    result = asyncio.run(run())
    assert result