from __future__ import annotations

import hashlib
from io import BytesIO
from typing import Any
from urllib.parse import quote, urlparse

import httpx
from PIL import Image, UnidentifiedImageError


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
        self._base_url = base_url.rstrip('/')
        self._timeout_seconds = max(1.0, float(timeout_seconds))
        self._client = client

    async def get_provider_status(self) -> Any:
        return await self._get('/api/v1/providers/status')

    async def list_projects(self, limit: int = 20) -> Any:
        if limit < 1 or limit > 50:
            raise ValueError('limit 必须在 1 到 50 之间')
        return await self._get('/api/v1/projects', params={'limit': limit})

    async def get_project(self, project_id: str) -> Any:
        return await self._get(f'/api/v1/projects/{quote(project_id, safe="")}')

    async def get_pipeline(self, project_id: str) -> Any:
        return await self._get(f'/api/v1/projects/{quote(project_id, safe="")}/pipeline')

    async def get_video(self, project_id: str) -> Any:
        return await self._get(f'/api/v1/projects/{quote(project_id, safe="")}/video')

    async def estimate_video_cost(self, project_id: str, plan_id: str) -> Any:
        return await self._get(
            f'/api/v1/projects/{quote(project_id, safe="")}/video-plan/{quote(plan_id, safe="")}/estimate'
        )

    async def create_project(self, product_name: str, product_note: str | None = None) -> Any:
        return await self._post(
            '/api/v1/projects',
            json={'product_name': product_name, 'product_note': product_note},
        )

    async def import_asset_from_url(
        self,
        project_id: str,
        image_url: str,
        *,
        allowed_hosts: tuple[str, ...],
        filename: str | None = None,
    ) -> Any:
        parsed = urlparse(image_url)
        if parsed.scheme != 'https' or not parsed.hostname:
            raise OneTakeApiError('素材 URL 必须是 HTTPS')
        if parsed.hostname.lower() not in allowed_hosts:
            raise OneTakeApiError('素材 URL 主机不在允许列表中')
        response = await self._request('GET', image_url, absolute=True)
        if response.status_code != 200:
            raise OneTakeApiError(f'素材下载失败：HTTP {response.status_code}')
        content = response.content
        if not content or len(content) > 10 * 1024 * 1024:
            raise OneTakeApiError('素材大小必须在 1B 到 10MB 之间')
        try:
            image = Image.open(BytesIO(content))
            image.verify()
            width, height = image.size
        except (UnidentifiedImageError, OSError) as exc:
            raise OneTakeApiError('素材不是有效图片') from exc
        if width <= 0 or height <= 0:
            raise OneTakeApiError('素材尺寸无效')
        metadata = {
            'original_filename': filename or parsed.path.rsplit('/', 1)[-1] or 'input.png',
            'mime_type': response.headers.get('content-type', 'image/png').split(';', 1)[0],
            'size_bytes': len(content),
            'width': width,
            'height': height,
            'sha256': hashlib.sha256(content).hexdigest(),
        }
        presign = await self._post(
            f'/api/v1/projects/{quote(project_id, safe="")}/assets/presign',
            json=metadata,
        )
        asset_id = presign['asset_id']
        upload = await self._request(
            'PUT',
            presign['upload_url'],
            absolute=True,
            content=content,
            headers={
                **presign.get('required_headers', {}),
                'Content-Type': metadata['mime_type'],
            },
        )
        if upload.status_code < 200 or upload.status_code >= 300:
            raise OneTakeApiError(f'素材上传失败：HTTP {upload.status_code}')
        return await self._post(
            f'/api/v1/projects/{quote(project_id, safe="")}/assets/{quote(asset_id, safe="")}/complete',
            json=metadata,
        )

    async def request_recognition(self, project_id: str) -> Any:
        return await self._post(f'/api/v1/projects/{quote(project_id, safe="")}/recognition')

    async def request_main_image(self, project_id: str) -> Any:
        return await self._post(f'/api/v1/projects/{quote(project_id, safe="")}/main-image')

    async def generate_script(
        self,
        project_id: str,
        *,
        pain_point: str,
        selling_points: list[str],
        usage_scenario: str,
        offer: str | None = None,
    ) -> Any:
        return await self._post(
            f'/api/v1/projects/{quote(project_id, safe="")}/script/generate',
            json={
                'pain_point': pain_point,
                'selling_points': selling_points,
                'usage_scenario': usage_scenario,
                'offer': offer,
            },
        )

    async def request_voice(
        self,
        project_id: str,
        *,
        voice_id: str,
        language: str = 'zh',
        speed: float = 1.0,
        enabled: bool = True,
        subtitle_enabled: bool = True,
    ) -> Any:
        return await self._post(
            f'/api/v1/projects/{quote(project_id, safe="")}/voice',
            json={
                'enabled': enabled,
                'subtitle_enabled': subtitle_enabled,
                'voice_id': voice_id,
                'language': language,
                'speed': speed,
            },
        )

    async def create_video_plan(
        self,
        project_id: str,
        *,
        mode: str,
        template_id: str | None = None,
    ) -> Any:
        return await self._post(
            f'/api/v1/projects/{quote(project_id, safe="")}/video-plan',
            json={'mode': mode, 'template_id': template_id},
        )

    async def request_video(self, project_id: str) -> Any:
        return await self._post(f'/api/v1/projects/{quote(project_id, safe="")}/video')

    async def _get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        response = await self._request('GET', path, params=params)
        return self._payload(response)

    async def _post(self, path: str, *, json: dict[str, Any] | None = None) -> Any:
        response = await self._request('POST', path, json=json)
        return self._payload(response)

    async def _request(
        self,
        method: str,
        path_or_url: str,
        *,
        absolute: bool = False,
        **kwargs: Any,
    ) -> httpx.Response:
        url = path_or_url if absolute else f'{self._base_url}{path_or_url}'
        try:
            if self._client is not None:
                response = await self._client.request(
                    method,
                    url,
                    timeout=self._timeout_seconds,
                    **kwargs,
                )
            else:
                async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                    response = await client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise OneTakeApiError('One Take API 不可用') from exc
        return response

    @staticmethod
    def _payload(response: httpx.Response) -> Any:
        try:
            payload = response.json()
        except ValueError as exc:
            raise OneTakeApiError(f'One Take API 返回非 JSON：HTTP {response.status_code}') from exc
        if response.status_code < 200 or response.status_code >= 300:
            detail = payload.get('detail') if isinstance(payload, dict) else None
            raise OneTakeApiError(f'One Take API 请求失败：{detail or response.status_code}')
        return payload.get('data', payload) if isinstance(payload, dict) else payload