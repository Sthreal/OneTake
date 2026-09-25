from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from onetake_mcp.approvals import ApprovalStore
from onetake_mcp.client import OneTakeClient
from onetake_mcp.config import Settings


def build_mcp(
    client: OneTakeClient,
    *,
    settings: Settings,
    approvals: ApprovalStore,
) -> FastMCP:
    mcp = FastMCP(
        'One Take',
        instructions='One Take project, pipeline, cost and controlled write tools.',
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
    async def onetake_get_mcp_capabilities() -> Any:
        """Read the enabled MCP write and paid capabilities."""
        return {
            'read_only': True,
            'write_enabled': settings.write_enabled,
            'paid_enabled': settings.paid_enabled,
            'asset_import_enabled': bool(settings.asset_hosts),
        }

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

    if settings.write_enabled:
        @mcp.tool()
        async def onetake_create_project(
            product_name: str,
            product_note: str | None = None,
        ) -> Any:
            """Create a new One Take project."""
            return await client.create_project(product_name, product_note)

        @mcp.tool()
        async def onetake_import_asset_url(
            project_id: str,
            image_url: str,
            filename: str | None = None,
        ) -> Any:
            """Import an HTTPS image URL into a One Take project."""
            return await client.import_asset_from_url(
                project_id,
                image_url,
                allowed_hosts=settings.asset_hosts,
                filename=filename,
            )

        @mcp.tool()
        async def onetake_request_recognition(project_id: str) -> Any:
            """Start product recognition for a project."""
            return await client.request_recognition(project_id)

        @mcp.tool()
        async def onetake_request_main_image(project_id: str) -> Any:
            """Start main-image generation for a project."""
            return await client.request_main_image(project_id)

        @mcp.tool()
        async def onetake_generate_script(
            project_id: str,
            pain_point: str,
            selling_points: list[str],
            usage_scenario: str,
            offer: str | None = None,
        ) -> Any:
            """Generate a script version from confirmed product facts."""
            return await client.generate_script(
                project_id,
                pain_point=pain_point,
                selling_points=selling_points,
                usage_scenario=usage_scenario,
                offer=offer,
            )

        @mcp.tool()
        async def onetake_create_video_plan(
            project_id: str,
            mode: str,
            template_id: str | None = None,
        ) -> Any:
            """Create a video plan for an existing project."""
            if mode not in {'avatar', 'product'}:
                raise ValueError('mode 必须是 avatar 或 product')
            return await client.create_video_plan(
                project_id,
                mode=mode,
                template_id=template_id,
            )

    if settings.write_enabled and settings.paid_enabled:
        @mcp.tool()
        async def onetake_request_voice(
            project_id: str,
            approval_id: str,
            voice_id: str,
            language: str = 'zh',
            speed: float = 1.0,
            subtitle_enabled: bool = True,
        ) -> Any:
            """Request paid voice generation after human approval."""
            approvals.consume(approval_id, action='voice', target=project_id)
            return await client.request_voice(
                project_id,
                voice_id=voice_id,
                language=language,
                speed=speed,
                subtitle_enabled=subtitle_enabled,
            )

        @mcp.tool()
        async def onetake_request_video(
            project_id: str,
            plan_id: str,
            approval_id: str,
        ) -> Any:
            """Request paid video generation after human approval."""
            approvals.consume(
                approval_id,
                action='video',
                target=f'{project_id}:{plan_id}',
            )
            return await client.request_video(project_id)

    if settings.write_enabled and settings.paid_enabled:
        @mcp.custom_route('/internal/approvals', methods=['POST'])
        async def create_approval(request: Request) -> JSONResponse:
            payload = await request.json()
            action = str(payload.get('action') or '')
            project_id = str(payload.get('project_id') or '')
            plan_id = str(payload.get('plan_id') or '')
            if action not in {'voice', 'video'}:
                return JSONResponse({'detail': 'unsupported approval action'}, status_code=400)
            if not project_id:
                return JSONResponse({'detail': 'project_id is required'}, status_code=400)
            if action == 'video' and not plan_id:
                return JSONResponse({'detail': 'plan_id is required'}, status_code=400)
            target = project_id if action == 'voice' else f'{project_id}:{plan_id}'
            record = approvals.create(
                action=action,
                target=target,
                summary=str(payload.get('summary') or action),
            )
            return JSONResponse(
                {
                    'approval_id': record.approval_id,
                    'action': record.action,
                    'target': record.target,
                    'expires_at': record.expires_at,
                }
            )

    return mcp