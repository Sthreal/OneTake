from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProductLayer:
    start: float
    length: float
    effect: str | None = None


@dataclass(frozen=True)
class CompositionRequest:
    base_video_bytes: bytes
    audio_bytes: bytes | None
    srt_bytes: bytes | None
    product_image_bytes: bytes | None
    overlay_product: bool
    duration_seconds: float
    width: int
    height: int
    fps: int
    motion_effect: str | None = None
    product_layers: list[ProductLayer] | None = None


class CompositionPort(Protocol):
    provider_name: str

    def compose(self, request: CompositionRequest) -> bytes:
        ...
