from __future__ import annotations

from collections.abc import Callable

import httpx

from onetake_api.integrations.media.video_utils import inspect_video_dimensions
from onetake_api.platform.errors import DomainError


class WanS2VError(DomainError):
    code = "VIDEO_PROVIDER_ERROR"
    http_status = 502
    retryable = True


class WanS2VAdapter:
    provider_name = "wan-s2v"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        resolution: str,
        max_seconds: int,
        upload_image: Callable[[bytes], str],
        upload_audio: Callable[[bytes], str],
        video_synthesis=None,
        inspect_dimensions: Callable[[bytes], tuple[int, int]] = inspect_video_dimensions,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self.resolution = resolution
        self._max_seconds = max(1, min(max_seconds, 60))
        self._upload_image = upload_image
        self._upload_audio = upload_audio
        self._inspect_dimensions = inspect_dimensions
        self._client = client or httpx.Client(timeout=120)
        if video_synthesis is None:
            from dashscope import VideoSynthesis
            video_synthesis = VideoSynthesis
        self._video_synthesis = video_synthesis

    def generate(
        self,
        *,
        image_bytes: bytes,
        audio_bytes: bytes,
        prompt: str,
        duration_seconds: int,
        resolution: str | None = None,
    ) -> tuple[bytes, str]:
        if not self._api_key:
            raise WanS2VError("DASHSCOPE_API_KEY 未配置")
        if not self.model:
            raise WanS2VError("WAN_S2V_MODEL 未配置")
        if not image_bytes:
            raise WanS2VError("Wan S2V 输入图片为空")
        if not audio_bytes:
            raise WanS2VError("Wan S2V 输入音频为空")
        image_url = self._upload_image(image_bytes)
        audio_url = self._upload_audio(audio_bytes)
        duration = min(self._max_seconds, max(1, int(round(duration_seconds))))
        selected_resolution = resolution or self.resolution
        try:
            response = self._video_synthesis.async_call(
                api_key=self._api_key,
                model=self.model,
                img_url=image_url,
                audio_url=audio_url,
                prompt=prompt,
                resolution=selected_resolution,
                duration=duration,
                prompt_extend=False,
                watermark=False,
            )
            if getattr(response, "status_code", 200) != 200:
                raise WanS2VError(f"Wan S2V 提交失败：{getattr(response, 'code', 'unknown')}")
            task_id = str(response.output.task_id)
            waited = self._video_synthesis.wait(task=task_id, api_key=self._api_key)
            if getattr(waited, "status_code", 200) != 200:
                raise WanS2VError(f"Wan S2V 任务失败：{getattr(waited, 'code', 'unknown')}")
            task_status = str(getattr(waited.output, "task_status", "")).upper()
            if task_status not in {"SUCCEEDED", "SUCCESS"}:
                detail = getattr(waited.output, "message", "") or getattr(waited, "message", "")
                raise WanS2VError(f"Wan S2V 任务状态 {task_status or 'UNKNOWN'}：{detail}")
            video_url = str(getattr(waited.output, "video_url", "") or "")
            if not video_url.startswith(("http://", "https://")):
                raise WanS2VError("Wan S2V 未返回有效成片地址")
        except WanS2VError:
            raise
        except Exception as exc:
            raise WanS2VError("Wan S2V 调用失败") from exc
        try:
            download = self._client.get(video_url, timeout=120)
            download.raise_for_status()
        except httpx.HTTPError as exc:
            raise WanS2VError("Wan S2V 成片下载失败") from exc
        if not download.content:
            raise WanS2VError("Wan S2V 返回空视频")
        width, height = self._inspect_dimensions(download.content)
        ratio_error = abs(width / height - 9 / 16) if height else 1
        if ratio_error > 0.02:
            raise WanS2VError(f"Wan S2V 输出比例错误：{width}x{height}")
        return download.content, task_id