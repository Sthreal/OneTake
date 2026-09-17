from typing import Protocol

from onetake_api.modules.asset.domain.model import Asset
from onetake_api.modules.recognition.domain import CandidateDraft


class RecognitionPort(Protocol):
    def recognize(self, assets: list[Asset]) -> list[CandidateDraft]: ...
