from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class VoiceSynthesisResult:
    audio_bytes: bytes
    mime_type: str
    duration_seconds: float
    timestamps: list


class TextToSpeechPort(Protocol):
    provider_name: str
    model: str

    def synthesize(self, *, text: str, voice_id: str, language: str, speed: float) -> VoiceSynthesisResult: ...
