from __future__ import annotations

import re
from io import BytesIO
from wave import open as wave_open

from onetake_api.modules.voice.port import VoiceSynthesisResult

_SPACE_RE = re.compile(r"\s+")


class MockVoiceAdapter:
    provider_name = "mock-cosyvoice-v2"
    model = "cosyvoice-v2"

    def synthesize(self, *, text: str, voice_id: str, language: str, speed: float) -> VoiceSynthesisResult:
        character_count = len(_SPACE_RE.sub("", text))
        # 短版对齐（2026-10-15）：比例必须与真实 TTS / 文案估算一致（实测 74 字 ≈ 14.4 秒 → 5.1 字/秒）。
        # 用旧的 3.5 会让 mock 配音凭空长 45%（67 字 → 19.1s），成片也跟着从 14s 变 19s。
        duration = min(30.0, max(3.0, round(character_count / max(0.5, speed * 5.1), 2)))
        sample_rate = 24000
        frame_count = int(duration * sample_rate)
        output = BytesIO()
        with wave_open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(b"\x00\x00" * frame_count)
        return VoiceSynthesisResult(
            audio_bytes=output.getvalue(),
            mime_type="audio/wav",
            duration_seconds=duration,
            timestamps=[{"text": text, "begin_time": 0, "end_time": int(duration * 1000)}],
        )
