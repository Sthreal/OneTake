from __future__ import annotations

import time
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
    default_base_url = "https://maas.qianwenaiapi.com"
    submit_path = "/api/v1/services/aigc/image2video/video-synthesis"
    task_path = "/api/v1/tasks"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        resolution: str,
        max_seconds: int,
        upload_image: Callable[[bytes], str],
        upload_audio: Callable[[bytes], str],
        base_url: str = default_base_url,
        poll_interval_seconds: float = 5.0,
        poll_timeout_seconds: float = 15 * 60,
        inspect_dimensions: Callable[[bytes], tuple[int, int]] = inspect_video_dimensions,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self.resolution = resolution
        self._max_seconds = max(1, min(max_seconds, 60))
        self._upload_image = upload_image
        self._upload_audio = upload_audio
        self._base_url = base_url.rstrip("/")
        self._poll_interval_seconds = max(0.0, float(poll_interval_seconds))
        self._poll_timeout_seconds = max(0.0, float(poll_timeout_seconds))
        self._inspect_dimensions = inspect_dimensions
        self._client = client or httpx.Client(timeout=120)

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
        task_id = self._submit(
            image_url=image_url,
            audio_url=audio_url,
            prompt=prompt,
            duration=duration,
            resolution=selected_resolution,
        )
        video_url = self._wait_for_video_url(task_id)
        video_bytes = self._download(video_url)
        width, height = self._inspect_dimensions(video_bytes)
        ratio_error = abs(width / height - 9 / 16) if height else 1
        if ratio_error > 0.02:
            raise WanS2VError(f"Wan S2V 输出比例错误：{width}x{height}")
        return video_bytes, task_id

    def _submit(
        self,
        *,
        image_url: str,
        audio_url: str,
        prompt: str,
        duration: int,
        resolution: str,
    ) -> str:
        payload = {
            "model": self.model,
            "input": {
                "image_url": image_url,
                "audio_url": audio_url,
                "prompt": prompt,
            },
            "parameters": {
                "resolution": resolution,
                "duration": duration,
                "prompt_extend": False,
                "watermark": False,
            },
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }
        if image_url.startswith("oss://") or audio_url.startswith("oss://"):
            headers["X-DashScope-OssResourceResolve"] = "enable"
        try:
            response = self._client.post(
                f"{self._base_url}{self.submit_path}",
                headers=headers,
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise WanS2VError("Wan S2V 提交请求失败") from exc
        data = self._parse_response(response, action="提交")
        output = data.get("output") if isinstance(data.get("output"), dict) else {}
        task_id = str(output.get("task_id") or data.get("task_id") or "").strip()
        if not task_id:
            raise WanS2VError("Wan S2V 未返回任务 ID")
        return task_id

    def _wait_for_video_url(self, task_id: str) -> str:
        deadline = time.monotonic() + self._poll_timeout_seconds
        while time.monotonic() <= deadline:
            data = self._get_task(task_id)
            output = data.get("output") if isinstance(data.get("output"), dict) else {}
            task_status = str(output.get("task_status") or output.get("status") or "").upper()
            if task_status in {"SUCCEEDED", "SUCCESS"}:
                video_url = self._extract_video_url(output)
                if not video_url.startswith(("http://", "https://")):
                    raise WanS2VError("Wan S2V 未返回有效成片地址")
                return video_url
            if task_status in {"FAILED", "CANCELED", "CANCELLED"}:
                detail = self._error_detail(output) or "无详情"
                raise WanS2VError(f"Wan S2V 任务状态 {task_status}：{detail}")
            if task_status not in {"PENDING", "RUNNING"}:
                raise WanS2VError(f"Wan S2V 任务状态 {task_status or 'UNKNOWN'}")
            time.sleep(self._poll_interval_seconds)
        raise WanS2VError("Wan S2V 任务超时")

    def _get_task(self, task_id: str) -> dict:
        try:
            response = self._client.get(
                f"{self._base_url}{self.task_path}/{task_id}",
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        except httpx.HTTPError as exc:
            raise WanS2VError("Wan S2V 轮询请求失败") from exc
        return self._parse_response(response, action="轮询")

    @staticmethod
    def _extract_video_url(output: dict) -> str:
        results = output.get("results")
        if isinstance(results, dict):
            return str(results.get("video_url") or "")
        if isinstance(results, list):
            for result in results:
                if isinstance(result, dict) and result.get("video_url"):
                    return str(result["video_url"])
        return str(output.get("video_url") or "")

    def _download(self, video_url: str) -> bytes:
        try:
            download = self._client.get(video_url, timeout=120)
            download.raise_for_status()
        except httpx.HTTPError as exc:
            raise WanS2VError("Wan S2V 成片下载失败") from exc
        if not download.content:
            raise WanS2VError("Wan S2V 返回空视频")
        return download.content

    @staticmethod
    def _parse_response(response: httpx.Response, *, action: str) -> dict:
        try:
            data = response.json()
        except ValueError as exc:
            raise WanS2VError(f"Wan S2V {action}响应格式错误") from exc
        if not isinstance(data, dict):
            raise WanS2VError(f"Wan S2V {action}响应格式错误")
        if response.status_code not in {200, 201, 202}:
            detail = WanS2VAdapter._error_detail(data) or f"HTTP {response.status_code}"
            raise WanS2VError(f"Wan S2V {action}失败：{detail}")
        return data

    @staticmethod
    def _error_detail(value: object) -> str:
        if not isinstance(value, dict):
            return ""
        candidates = [value.get("code"), value.get("message")]
        output = value.get("output")
        if isinstance(output, dict):
            candidates.extend([output.get("code"), output.get("message")])
        details = [str(item) for item in candidates if item]
        return " / ".join(dict.fromkeys(details))
