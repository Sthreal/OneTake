from __future__ import annotations

from collections.abc import Callable

import subprocess
import tempfile
from pathlib import Path

import httpx
from imageio_ffmpeg import get_ffmpeg_exe

from onetake_api.integrations.media.image_utils import pad_image_to_9_16
from onetake_api.integrations.media.video_utils import inspect_video_dimensions
from onetake_api.platform.errors import DomainError


class WanI2VError(DomainError):
    code = "VIDEO_PROVIDER_ERROR"
    http_status = 502
    retryable = True


class VideoContractError(DomainError):
    code = "VIDEO_CONTRACT_VIOLATION"
    http_status = 502
    retryable = True


# WAN I2V 的 resolution 是「档位」，Provider 按档位返回固定尺寸（竖屏 9:16）。
# 段级生成请求的是档位，所以契约校验必须以档位尺寸为基准，而不是成片方案尺寸。
WAN_I2V_RESOLUTION_SIZES: dict[str, tuple[int, int]] = {
    "720P": (720, 1280),
    "1080P": (1080, 1920),
}


def resolution_output_size(resolution: str) -> tuple[int, int] | None:
    """该分辨率档位对应的输出尺寸；未知档位返回 None，调用方回退成比例校验。"""
    return WAN_I2V_RESOLUTION_SIZES.get(resolution)


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
        prepare_image: Callable[[bytes], bytes] = pad_image_to_9_16,
        inspect_dimensions: Callable[[bytes], tuple[int, int]] = inspect_video_dimensions,
        client: httpx.Client | None = None,
        expected_width: int | None = None,
        expected_height: int | None = None,
        duration_tolerance_seconds: float = 0.2,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self.resolution = resolution
        self._max_seconds = max(1, min(max_seconds, 30))
        self._upload_image = upload_image
        self._prepare_image = prepare_image
        self._inspect_dimensions = inspect_dimensions
        self._expected_width = expected_width
        self._expected_height = expected_height
        self._duration_tolerance = max(0.0, float(duration_tolerance_seconds))
        self._client = client or httpx.Client(timeout=120)
        if video_synthesis is None:
            from dashscope import VideoSynthesis
            video_synthesis = VideoSynthesis
        self._video_synthesis = video_synthesis

    def generate(self, *, image_bytes: bytes, prompt: str, duration_seconds: int, negative_prompt: str | None = None) -> tuple[bytes, str]:
        if not self._api_key:
            raise WanI2VError("DASHSCOPE_API_KEY 未配置")
        if not self.model:
            raise WanI2VError("WAN_I2V_MODEL 未配置")
        if not image_bytes:
            raise WanI2VError("WAN_I2V 输入图片为空")
        try:
            prepared_image = self._prepare_image(image_bytes)
        except Exception as exc:
            raise WanI2VError("WAN_I2V 输入图比例处理失败") from exc
        image_url = self._upload_image(prepared_image)
        duration = min(self._max_seconds, max(1, int(round(duration_seconds))))
        return self._execute_task(
            call_kwargs={
                "api_key": self._api_key, "model": self.model, "img_url": image_url,
                "prompt": prompt, "resolution": self.resolution, "duration": duration,
                "negative_prompt": negative_prompt or "", "prompt_extend": False, "watermark": False,
            },
            label="WAN_I2V",
            duration=duration,
        )

    def _execute_task(self, *, call_kwargs: dict, label: str, duration: int) -> tuple[bytes, str]:
        """提交 → 轮询 → 下载 → 契约校验。i2v 与 kf2v 共用同一套逻辑与校验口径。"""
        try:
            response = self._video_synthesis.async_call(**call_kwargs)
            if getattr(response, "status_code", 200) != 200:
                raise WanI2VError(f"{label} 提交失败：{getattr(response, 'code', 'unknown')}")
            task_id = str(response.output.task_id)
            waited = self._video_synthesis.wait(task=task_id, api_key=self._api_key)
            if getattr(waited, "status_code", 200) != 200:
                raise WanI2VError(f"{label} 任务失败：{getattr(waited, 'code', 'unknown')}")
            task_status = str(getattr(waited.output, "task_status", "")).upper()
            if task_status not in {"SUCCEEDED", "SUCCESS"}:
                detail = getattr(waited.output, "message", "") or getattr(waited, "message", "")
                raise WanI2VError(f"{label} 任务状态 {task_status or 'UNKNOWN'}：{detail}")
            video_url = str(getattr(waited.output, "video_url", "") or "")
            if not video_url.startswith(("http://", "https://")):
                raise WanI2VError(f"{label} 未返回有效成片地址")
        except WanI2VError:
            raise
        except Exception as exc:
            raise WanI2VError(f"{label} 调用失败") from exc
        try:
            download = self._client.get(video_url, timeout=120)
            download.raise_for_status()
        except httpx.HTTPError as exc:
            raise WanI2VError(f"{label} 成片下载失败") from exc
        if not download.content:
            raise WanI2VError(f"{label} 返回空视频")
        video_bytes = download.content
        width, height = self._inspect_dimensions(video_bytes)
        if self._expected_width and self._expected_height:
            if (width, height) != (self._expected_width, self._expected_height):
                try:
                    video_bytes = self._normalize_video_size(video_bytes, self._expected_width, self._expected_height)
                except Exception as exc:
                    # 根因是「尺寸不符」，必须保留契约错误类型供调用方判定（重试 / 降级）
                    raise VideoContractError(
                        f"{label} 输出尺寸 {width}x{height} 与预期 "
                        f"{self._expected_width}x{self._expected_height} 不一致，且归一化失败"
                    ) from exc
                width, height = self._inspect_dimensions(video_bytes)
            if (width, height) != (self._expected_width, self._expected_height):
                raise VideoContractError(f"{label} 输出尺寸 {width}x{height} 与预期 {self._expected_width}x{self._expected_height} 不一致")
            self._validate_duration(video_bytes, duration)
        else:
            ratio_error = abs(width / height - 9 / 16) if height else 1
            if ratio_error > 0.02:
                raise WanI2VError(f"{label} 输出比例错误：{width}x{height}")
        return video_bytes, task_id

    @staticmethod
    def _normalize_video_size(video_bytes: bytes, width: int, height: int) -> bytes:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = root / "input.mp4"
            output_path = root / "output.mp4"
            input_path.write_bytes(video_bytes)
            command = [
                get_ffmpeg_exe(),
                "-y",
                "-i",
                str(input_path),
                "-vf",
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "copy",
                str(output_path),
            ]
            subprocess.run(command, check=True, capture_output=True, text=True)
            return output_path.read_bytes()

    def _validate_duration(self, video_bytes: bytes, expected_seconds: int) -> None:
        from onetake_api.integrations.media.video_utils import inspect_video_duration
        actual = inspect_video_duration(video_bytes)
        if abs(actual - expected_seconds) > self._duration_tolerance:
            raise VideoContractError(f"WAN_I2V 输出时长 {actual:.2f}s 与预期 {expected_seconds}s 不一致")
