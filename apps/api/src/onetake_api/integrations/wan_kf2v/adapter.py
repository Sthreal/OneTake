"""Wan 首尾帧生视频适配器（Phase 2）。

为什么需要它（对应总体方案 §6）：
现有的"续段"做法是把上一段成片的**尾帧抽出来**当作下一段的首帧——多一次抽帧、多一次压缩，
而且转场只能靠硬拼接。kf2v 允许一次调用同时给"首帧 + 尾帧"，让**转场在片段内部生成**，
拼接处不再有跳变。

复用 i2v 适配器的提交流程与契约校验（`WanI2VAdapter._execute_task`），只替换输入参数，
保证两条路径的尺寸/时长/比例口径完全一致。
"""
from __future__ import annotations

from onetake_api.integrations.wan_i2v.adapter import WanI2VAdapter, WanI2VError


class WanKf2VAdapter(WanI2VAdapter):
    provider_name = "wan-kf2v"

    def generate_pair(
        self,
        *,
        first_frame_bytes: bytes,
        last_frame_bytes: bytes,
        prompt: str,
        duration_seconds: int,
        negative_prompt: str | None = None,
    ) -> tuple[bytes, str]:
        if not self._api_key:
            raise WanI2VError("DASHSCOPE_API_KEY 未配置")
        if not self.model:
            raise WanI2VError("WAN_KF2V_MODEL 未配置")
        if not first_frame_bytes or not last_frame_bytes:
            raise WanI2VError("WAN_KF2V 首帧或尾帧为空")
        try:
            first_url = self._upload_image(self._prepare_image(first_frame_bytes))
            last_url = self._upload_image(self._prepare_image(last_frame_bytes))
        except Exception as exc:
            raise WanI2VError("WAN_KF2V 输入帧处理失败") from exc
        duration = min(self._max_seconds, max(1, int(round(duration_seconds))))
        return self._execute_task(
            call_kwargs={
                "api_key": self._api_key, "model": self.model,
                "first_frame_url": first_url, "last_frame_url": last_url,
                "prompt": prompt, "resolution": self.resolution, "duration": duration,
                "negative_prompt": negative_prompt or "", "prompt_extend": False, "watermark": False,
            },
            label="WAN_KF2V",
            duration=duration,
        )