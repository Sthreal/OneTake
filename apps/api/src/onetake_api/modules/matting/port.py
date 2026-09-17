from typing import Protocol


class MattingPort(Protocol):
    provider_name: str

    def remove_background(self, *, image_bytes: bytes) -> bytes: ...
