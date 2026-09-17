from typing import Protocol


class ImageEditPort(Protocol):
    provider_name: str

    def edit(self, *, image_bytes: bytes, mime_type: str) -> bytes: ...
