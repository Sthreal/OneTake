"""Wan 参考生视频（r2v）适配器（Phase 3）。

为什么走 REST 而不是 dashscope SDK：r2v 的 `input.media` 是一个"图/视频混合参考"数组
（`first_frame` / `reference_image` / `reference_video` + 可选音色），SDK 的
`VideoSynthesis.async_call` 没有对应参数；官方文档给的就是 REST 形态，因此这里直接按文档调用。

硬约束（与 `modules/video_plan/one_shot.py` 保持一致）：
- `reference_image` + `reference_video` 合计 ≤ 5，`first_frame` 最多 1 张
- `reference_image` 不支持透明通道 → 上传前统一 flatten
"""
from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from onetake_api.integrations.media.image_utils import flatten_for_reference
from onetake_api.integrations.media.video_utils import inspect_video_dimensions
from onetake_api.platform.errors import DomainError

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com"
MAX_MEDIA_ITEMS = 5
MIN_DURATION_SECONDS = 2
MAX_DURATION_SECONDS = 15


class WanR2VError(DomainError):
    code = "WAN_R2V_ERROR"
    http_status = 502
    retryable = True


class WanR2VAdapter:
    provider_name = "wan-r2v"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        upload_media: Callable[[bytes, str], str],
        resolution: str = "720P",
        max_seconds: int = MAX_DURATION_SECONDS,
        base_url: str = DEFAULT_BASE_URL,
        client: httpx.Client | None = None,
        poll_interval_seconds: float = 3.0,
        poll_timeout_seconds: float = 600.0,
        prepare_image: Callable[[bytes], bytes] = flatten_for_reference,
        inspect_dimensions: Callable[[bytes], tuple[int, int]] = inspect_video_dimensions,
        expected_width: int | None = None,
        expected_height: int | None = None,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self.resolution = resolution
        self._max_seconds = max(MIN_DURATION_SECONDS, min(int(max_seconds), MAX_DURATION_SECONDS))
        self._upload_media = upload_media
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=120)
        self._poll_interval = max(0.1, float(poll_interval_seconds))
        self._poll_timeout = max(1.0, float(poll_timeout_seconds))
        self._prepare_image = prepare_image
        self._inspect_dimensions = inspect_dimensions
        self._expected_width = expected_width
        self._expected_height = expected_height

    def generate_film(
        self,
        *,
        first_frame_bytes: bytes,
        reference_images: list[bytes],
        prompt: str,
        duration_seconds: float,
        seed: int | None = None,
    ) -> tuple[bytes, str]:
        if not self._api_key:
            raise WanR2VError("DASHSCOPE_API_KEY 未配置")
        if not self.model:
            raise WanR2VError("WAN_R2V_MODEL 未配置")
        if not first_frame_bytes:
            raise WanR2VError("WAN_R2V 缺少首帧")
        if not prompt:
            raise WanR2VError("WAN_R2V 缺少提示词")
        refs = list(reference_images)[: MAX_MEDIA_ITEMS - 1]
        media: list[dict] = []
        try:
            media.append({"type": "first_frame", "url": self._upload_media(self._prepare_image(first_frame_bytes), "r2v-first.png")})
            for index, image in enumerate(refs, start=2):
                media.append(
                    {"type": "reference_image", "url": self._upload_media(self._prepare_image(image), f"r2v-ref-{index}.png")}
                )
        except DomainError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise WanR2VError("WAN_R2V 参考素材上传失败") from exc

        duration = max(MIN_DURATION_SECONDS, min(self._max_seconds, int(round(duration_seconds))))
        parameters: dict = {
            "resolution": self.resolution,
            "ratio": "9:16",
            "duration": duration,
            "prompt_extend": False,
            "watermark": False,
        }
        if seed is not None:
            parameters["seed"] = int(seed)
        payload = {"model": self.model, "input": {"prompt": prompt, "media": media}, "parameters": parameters}
        task_id = self._submit(payload)
        video_url = self._wait(task_id)
        video_bytes = self._download(video_url)
        self._validate(video_bytes, duration)
        return video_bytes, task_id

    def _submit(self, payload: dict) -> str:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }
        # 参考素材是本项目上传的 oss:// 临时文件：必须显式让 DashScope 解析 OSS 资源，
        # 否则任务会以 "Failed to download oss://..." 失败（与 S2V 适配器同一口径）。
        if any(str(item.get("url", "")).startswith("oss://") for item in payload.get("input", {}).get("media", [])):
            headers["X-DashScope-OssResourceResolve"] = "enable"
        try:
            response = self._client.post(
                f"{self._base_url}/api/v1/services/aigc/video-generation/video-synthesis",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPStatusError as exc:
            # 带上 HTTP 状态与响应体片段：否则"提交失败"四个字什么也说明不了（2026-10-15 实测踩过）
            body = (exc.response.text or "")[:200].replace("\n", " ")
            raise WanR2VError(f"WAN_R2V 提交失败（HTTP {exc.response.status_code}：{body}）") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise WanR2VError(f"WAN_R2V 提交失败（{type(exc).__name__}：{exc}）") from exc
        task_id = str(body.get("output", {}).get("task_id") or "")
        if not task_id:
            raise WanR2VError("WAN_R2V 未返回 task_id")
        return task_id

    def _wait(self, task_id: str) -> str:
        deadline = time.monotonic() + self._poll_timeout
        while True:
            try:
                response = self._client.get(
                    f"{self._base_url}/api/v1/tasks/{task_id}",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                response.raise_for_status()
                output = response.json().get("output", {})
            except (httpx.HTTPError, ValueError) as exc:
                raise WanR2VError("WAN_R2V 任务查询失败") from exc
            status = str(output.get("task_status", "")).upper()
            if status in {"SUCCEEDED", "SUCCESS"}:
                video_url = str(output.get("video_url") or "")
                if not video_url.startswith(("http://", "https://")):
                    raise WanR2VError("WAN_R2V 未返回有效成片地址")
                return video_url
            if status in {"FAILED", "CANCELED", "UNKNOWN"}:
                raise WanR2VError(f"WAN_R2V 任务状态 {status}：{output.get('message', '')}")
            if time.monotonic() >= deadline:
                raise WanR2VError("WAN_R2V 任务超时")
            time.sleep(self._poll_interval)

    def _download(self, video_url: str) -> bytes:
        try:
            response = self._client.get(video_url, timeout=120)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise WanR2VError("WAN_R2V 成片下载失败") from exc
        if not response.content:
            raise WanR2VError("WAN_R2V 返回空视频")
        return response.content

    def _validate(self, video_bytes: bytes, duration: int) -> None:
        width, height = self._inspect_dimensions(video_bytes)
        if self._expected_width and self._expected_height:
            if (width, height) != (self._expected_width, self._expected_height):
                raise WanR2VError(
                    f"WAN_R2V 输出尺寸 {width}x{height} 与预期 {self._expected_width}x{self._expected_height} 不一致"
                )
            return
        if height and abs(width / height - 9 / 16) > 0.02:
            raise WanR2VError(f"WAN_R2V 输出比例错误：{width}x{height}")