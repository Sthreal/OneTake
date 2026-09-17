from dataclasses import dataclass
from typing import Protocol

from onetake_api.modules.recognition.domain import CandidateDraft


@dataclass(frozen=True)
class RecognitionImage:
    asset_id: str
    original_filename: str
    mime_type: str
    sha256: str | None
    content: bytes | None = None


class RecognitionPort(Protocol):
    provider_name: str
    requires_images: bool

    def recognize(
        self,
        *,
        project_name: str,
        product_note: str | None,
        images: list[RecognitionImage],
    ) -> list[CandidateDraft]: ...
