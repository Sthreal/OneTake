import asyncio

from onetake_mcp.approvals import ApprovalStore
from onetake_mcp.config import Settings
from onetake_mcp.tools import build_mcp


class FakeClient:
    async def get_provider_status(self):
        return [{'capability': 'avatar_video'}]

    async def list_projects(self, limit=20):
        return []

    async def get_project(self, project_id):
        return {'project_id': project_id}

    async def get_pipeline(self, project_id):
        return {'project_id': project_id}

    async def get_video(self, project_id):
        return {'project_id': project_id}

    async def estimate_video_cost(self, project_id, plan_id):
        return {'project_id': project_id, 'plan_id': plan_id}


def _settings(*, write=False, paid=False):
    return Settings(
        api_base_url='http://test',
        service_token='mcp-token',
        approval_token='approval-token',
        request_timeout_seconds=1,
        write_enabled=write,
        paid_enabled=paid,
        asset_hosts=('cdn.example',),
    )


def test_mcp_exposes_read_only_tool_contract() -> None:
    async def run():
        mcp = build_mcp(FakeClient(), settings=_settings(), approvals=ApprovalStore())
        tools = await mcp.list_tools()
        return [tool.name for tool in tools]

    assert set(asyncio.run(run())) == {
        'onetake_get_provider_status',
        'onetake_list_projects',
        'onetake_get_project',
        'onetake_get_pipeline',
        'onetake_get_video',
        'onetake_estimate_video_cost',
        'onetake_get_mcp_capabilities',
    }


def test_write_tools_are_hidden_until_enabled() -> None:
    async def run():
        mcp = build_mcp(
            FakeClient(),
            settings=_settings(write=True),
            approvals=ApprovalStore(),
        )
        tools = await mcp.list_tools()
        return {tool.name for tool in tools}

    names = asyncio.run(run())
    assert 'onetake_create_project' in names
    assert 'onetake_import_asset_url' in names
    assert 'onetake_create_video_plan' in names
    assert 'onetake_request_video' not in names


def test_paid_tools_require_paid_flag() -> None:
    async def run():
        mcp = build_mcp(
            FakeClient(),
            settings=_settings(write=True, paid=True),
            approvals=ApprovalStore(),
        )
        tools = await mcp.list_tools()
        return {tool.name for tool in tools}

    names = asyncio.run(run())
    assert 'onetake_request_voice' in names
    assert 'onetake_request_video' in names