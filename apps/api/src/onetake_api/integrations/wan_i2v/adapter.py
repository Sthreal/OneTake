from __future__ import annotations

from collections.abc import Callable

import httpx

from onetake_api.platform.errors import DomainError


class WanI2VError(DomainError):
    code = "VIDEO_PROVIDER_ERROR"
    http_status = 502
    retryable = True


class WanI2VAdapter:
    provider_name = "wan-i2v"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        resolution: str,
        max_seconds: int,
        upload_image: Callable[[bytes], str],
        video_synthesis=None,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self.resolution = resolution
        self._max_seconds = max(1, min(max_seconds, 30))
        self._upload_image = upload_image
        self._client = client or httpx.Client(timeout=120)
        if video_synthesis is None:
            from dashscope import VideoSynthesis
            video_synthesis = VideoSynthesis
        self._video_synthesis = video_synthesis

    def generate(self, *, image_bytes: bytes, prompt: str, duration_seconds: int) -> tuple[bytes, str]:
        if not self._api_key:
            raise WanI2VError("DASHSCOPE_API_KEY 未配置")
        if not self.model:
            raise WanI2VError("WAN_I2V_MODEL 未配置")
        if not image_bytes:
            raise WanI2VError("WAN_I2V 输入图片为空")
        image_url = self._upload_image(image_bytes)
        duration = min(self._max_seconds, max(1, int(round(duration_seconds))))
        try:
            response = self._video_synthesis.async_call(
                api_key=self._api_key,
                model=self.model,
                img_url=image_url,
                prompt=prompt,
                resolution=self.resolution,
                ratio="9:16",
                duration=duration,
                prompt_extend=False,
                watermark=False,
            )
            if getattr(response, "status_code", 200) != 200:
                raise WanI2VError(f"WAN_I2V 提交失败：{getattr(response, 'code', 'unknown')}")
            task_id = str(response.output.task_id)
            waited = self._video_synthesis.wait(task=task_id, api_key=self._api_key)
            if getattr(waited, "status_code", 200) != 200:
                raise WanI2VError(f"WAN_I2V 任务失败：{getattr(waited, 'code', 'unknown')}")
            task_status = str(getattr(waited.output, "task_status", "")).upper()
            if task_status not in {"SUCCEEDED", "SUCCESS"}:
                detail = getattr(waited.output, "message", "") or getattr(waited, "message", "")
                raise WanI2VError(f"WAN_I2V 任务状态 {task_status or 'UNKNOWN'}：{detail}")
            video_url = str(getattr(waited.output, "video_url", "") or "")
            if not video_url.startswith(("http://", "https://")):
                raise WanI2VError("WAN_I2V 未返回有效成片地址")
        except WanI2VError:
            raise
        except Exception as exc:
            raise WanI2VError("WAN_I2V 调用失败") from exc
        try:
            download = self._client.get(video_url, timeout=120)
            download.raise_for_status()
        except httpx.HTTPError as exc:
            raise WanI2VError("WAN_I2V 成片下载失败") from exc
        if not download.content:
            raise WanI2VError("WAN_I2V 返回空视频")
        return download.content, task_id
