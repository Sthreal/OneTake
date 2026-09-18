from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from onetake_api.integrations.media.subtitle_burner import burn_subtitles
from onetake_api.modules.composition.port import CompositionRequest
from onetake_api.platform.errors import DomainError

REQUEST_TIMEOUT_SECONDS = 60


class ShotstackError(DomainError):
    code = "COMPOSITION_PROVIDER_ERROR"
    http_status = 502
    retryable = True


class ShotstackCompositionAdapter:
    def __init__(
        self,
        *,
        api_key: str,
        environment: str,
        api_base: str,
        poll_interval_seconds: float = 2.0,
        poll_timeout_seconds: int = 600,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._api_key = api_key
        self._environment = environment
        self._api_base = api_base.rstrip("/")
        self._poll_interval_seconds = poll_interval_seconds
        self._poll_timeout_seconds = poll_timeout_seconds
        self._client = client or httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)
        self._sleep = sleep
        self._monotonic = monotonic
        self.provider_name = f"shotstack-{environment}"

    def compose(self, request: CompositionRequest) -> bytes:
        if not self._api_key:
            raise ShotstackError("Shotstack API Key 未配置")
        if not request.base_video_bytes:
            raise ShotstackError("Shotstack 基础视频为空")

        base_video = request.base_video_bytes
        if request.srt_bytes:
            base_video = burn_subtitles(
                base_video_bytes=base_video,
                srt_bytes=request.srt_bytes,
                duration_seconds=request.duration_seconds,
                fps=request.fps,
            )
        base_video_url = self._upload(base_video, "base.mp4", "video/mp4")
        audio_url = self._upload(request.audio_bytes, "voice.wav", "audio/wav") if request.audio_bytes else None
        product_image_url = (
            self._upload(request.product_image_bytes, "product.png", "image/png")
            if request.overlay_product and request.product_image_bytes
            else None
        )
        payload = self._build_edit_payload(
            request=request,
            base_video_url=base_video_url,
            audio_url=audio_url,
            product_image_url=product_image_url,
        )
        render_id = self._submit_render(payload)
        output_url = self._wait_for_render(render_id)
        return self._download(output_url)

    def _upload(self, content: bytes, filename: str, mime_type: str) -> str:
        response = self._client.post(
            f"{self._api_base}/ingest/{self._environment}/upload",
            headers=self._headers(),
            json={"filename": filename},
        )
        body = self._json(response, "获取 Shotstack 上传地址失败")
        try:
            data = body["data"]
            upload_id = str(data["id"])
            signed_url = str(data["attributes"]["url"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ShotstackError("Shotstack 上传响应结构无效") from exc

        upload_response = self._client.put(
            signed_url,
            content=content,
            headers={"Content-Type": mime_type},
        )
        if upload_response.is_error:
            raise ShotstackError("Shotstack 素材上传失败")

        source_url = self._wait_for_source(upload_id)
        if not source_url:
            raise ShotstackError("Shotstack 未返回素材地址")
        return source_url

    def _wait_for_source(self, source_id: str) -> str:
        deadline = self._monotonic() + self._poll_timeout_seconds
        while True:
            response = self._client.get(
                f"{self._api_base}/ingest/{self._environment}/sources/{source_id}",
                headers=self._headers(),
            )
            body = self._json(response, "读取 Shotstack 素材状态失败")
            try:
                attributes = body["data"]["attributes"]
                status = str(attributes["status"]).lower()
                source_url = attributes.get("source")
            except (KeyError, TypeError, ValueError) as exc:
                raise ShotstackError("Shotstack 素材状态结构无效") from exc
            if status == "ready" and source_url:
                return str(source_url)
            if status in {"failed", "deleted"}:
                raise ShotstackError("Shotstack 素材导入失败")
            if self._monotonic() >= deadline:
                raise ShotstackError("Shotstack 素材导入超时")
            self._sleep(self._poll_interval_seconds)

    def _submit_render(self, payload: dict[str, Any]) -> str:
        response = self._client.post(
            f"{self._api_base}/edit/{self._environment}/render",
            headers={**self._headers(), "Content-Type": "application/json"},
            json=payload,
        )
        body = self._json(response, "提交 Shotstack 渲染任务失败")
        try:
            return str(body["response"]["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ShotstackError("Shotstack 渲染响应结构无效") from exc

    def _wait_for_render(self, render_id: str) -> str:
        deadline = self._monotonic() + self._poll_timeout_seconds
        while True:
            response = self._client.get(
                f"{self._api_base}/edit/{self._environment}/render/{render_id}",
                headers=self._headers(),
            )
            body = self._json(response, "读取 Shotstack 渲染状态失败")
            try:
                attributes = body["response"]
                status = str(attributes["status"]).lower()
                output_url = attributes.get("url")
            except (KeyError, TypeError, ValueError) as exc:
                raise ShotstackError("Shotstack 渲染状态结构无效") from exc
            if status == "done":
                if not output_url:
                    raise ShotstackError("Shotstack 渲染完成但未返回成片地址")
                return str(output_url)
            if status == "failed":
                raise ShotstackError("Shotstack 渲染失败")
            if self._monotonic() >= deadline:
                raise ShotstackError("Shotstack 渲染超时")
            self._sleep(self._poll_interval_seconds)

    def _download(self, url: str) -> bytes:
        content = b""
        last_error: httpx.HTTPError | None = None
        for _attempt in range(5):
            headers = {"Range": f"bytes={len(content)}-"} if content else {}
            try:
                with self._client.stream("GET", url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                    response.raise_for_status()
                    if content and response.status_code == 200:
                        content = b""
                    for chunk in response.iter_bytes(256 * 1024):
                        content += chunk
                if content:
                    return content
            except httpx.HTTPError as exc:
                last_error = exc
                self._sleep(2)
        raise ShotstackError("Shotstack 成片下载失败") from last_error

    def _json(self, response: httpx.Response, message: str) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            raise ShotstackError(f"{message}：响应不是 JSON") from exc
        if response.is_error:
            detail = body.get("error") if isinstance(body, dict) else None
            if isinstance(detail, dict):
                detail = detail.get("message") or detail.get("detail") or detail
            raise ShotstackError(f"{message}：{detail or response.status_code}")
        if not isinstance(body, dict):
            raise ShotstackError(f"{message}：响应不是对象")
        return body

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self._api_key, "Accept": "application/json"}

    @staticmethod
    def _build_edit_payload(
        *,
        request: CompositionRequest,
        base_video_url: str,
        audio_url: str | None,
        product_image_url: str | None,
    ) -> dict[str, Any]:
        tracks: list[dict[str, Any]] = []
        if product_image_url:
            tracks.append({
                "clips": [{
                    "asset": {"type": "image", "src": product_image_url},
                    "start": 0,
                    "length": request.duration_seconds,
                    "fit": "contain",
                    "position": "center",
                }],
            })
        tracks.append({
            "clips": [{
                "asset": {"type": "video", "src": base_video_url},
                "start": 0,
                "length": request.duration_seconds,
                "fit": "cover",
                "position": "center",
            }],
        })
        if audio_url:
            tracks.append({
                "clips": [{
                    "asset": {"type": "audio", "src": audio_url},
                    "start": 0,
                    "length": request.duration_seconds,
                }],
            })
        timeline: dict[str, Any] = {"background": "#000000", "tracks": tracks}
        return {
            "timeline": timeline,
            "output": {
                "format": "mp4",
                "fps": request.fps,
                "size": {"width": request.width, "height": request.height},
            },
        }
