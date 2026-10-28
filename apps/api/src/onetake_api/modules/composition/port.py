"""合成端口（CompositionPort）。

**M4-03 之后本端口只做四件事**：拼接、混音、字幕、AIGC 标识 —— **不再叠商品**。
商品入画只有一条路：关键帧里商品就已经在画面中（「生成背景 + 合成叠商品」路线已废弃）。

因此 `CompositionRequest` 不再携带 `overlay_product` / `product_image_bytes` / `product_layers`：
保留恒 false 的字段会留下"以为还能叠商品"的误导（方案 M4-03 §七）。
"""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CompositionRequest:
    base_video_bytes: bytes
    audio_bytes: bytes | None
    srt_bytes: bytes | None
    duration_seconds: float
    width: int
    height: int
    fps: int
    motion_effect: str | None = None
    # 方案级合成覆盖（S4-④a）：None = 跟全局配置（`Settings`）—— 尾部默认值保证既有调用点零改动
    caption_style: str | None = None
    bgm_enabled: bool | None = None
    bgm_gain_db: float | None = None


class CompositionPort(Protocol):
    provider_name: str

    def compose(self, request: CompositionRequest) -> bytes:
        ...