from __future__ import annotations

from typing import Protocol


class AvatarVideoPort(Protocol):
    provider_name: str

    def generate(
        self,
        *,
        image_bytes: bytes,
        audio_bytes: bytes,
        prompt: str,
        duration_seconds: int,
        resolution: str,
    ) -> tuple[bytes, str]:
        ...