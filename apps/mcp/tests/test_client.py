import asyncio

import httpx
import pytest

from onetake_mcp.client import OneTakeApiError, OneTakeClient


def test_client_reads_provider_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/providers/status"
        return httpx.Response(200, json={"data": [{"capability": "recognition"}], "request_id": "req"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            client = OneTakeClient(base_url="http://test", client=http_client)
            return await client.get_provider_status()

    assert asyncio.run(run()) == [{"capability": "recognition"}]


def test_client_surfaces_api_error_without_payload_leak() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "项目不存在", "secret": "must-not-return"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            client = OneTakeClient(base_url="http://test", client=http_client)
            with pytest.raises(OneTakeApiError, match="项目不存在"):
                await client.get_project("missing")

    asyncio.run(run())