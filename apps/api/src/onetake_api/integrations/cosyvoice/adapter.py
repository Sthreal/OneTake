from __future__ import annotations

from io import BytesIO
from wave import open as wave_open

from onetake_api.modules.voice.port import VoiceSynthesisResult
from onetake_api.platform.errors import DomainError

REQUEST_TIMEOUT_MILLIS = 120000


class CosyVoiceError(DomainError):
    code = "VOICE_PROVIDER_ERROR"
    http_status = 502
    retryable = True


class CosyVoiceV2Adapter:
    provider_name = "cosyvoice-v2"

    def __init__(self, *, api_key: str, model: str) -> None:
        self._api_key = api_key
        self.model = model

    def synthesize(self, *, text: str, voice_id: str, language: str, speed: float) -> VoiceSynthesisResult:
        if not self._api_key:
            raise CosyVoiceError("DASHSCOPE_API_KEY 未配置")
        try:
            import dashscope
            from dashscope.audio.tts_v2 import AudioFormat, SpeechSynthesizer

            dashscope.api_key = self._api_key
            synthesizer = SpeechSynthesizer(
                model=self.model,
                voice=voice_id,
                format=AudioFormat.WAV_48000HZ_MONO_16BIT,
                speech_rate=speed,
                language_hints=[language],
            )
            audio = synthesizer.call(text, timeout_millis=REQUEST_TIMEOUT_MILLIS)
        except Exception as exc:
            raise CosyVoiceError("CosyVoice V2 配音请求失败") from exc
        if not audio:
            raise CosyVoiceError("CosyVoice V2 未返回音频")
        try:
            with wave_open(BytesIO(audio), "rb") as wav:
                frame_rate = float(wav.getframerate())
                declared_frames = wav.getnframes()
                bytes_per_frame = max(1, wav.getnchannels() * wav.getsampwidth())
                actual_frames = max(0, len(audio) - 44) // bytes_per_frame
                frame_count = actual_frames if declared_frames > actual_frames * 2 else declared_frames
                duration = round(frame_count / frame_rate, 3)
        except Exception as exc:
            raise CosyVoiceError("CosyVoice V2 返回音频无效") from exc
        return VoiceSynthesisResult(audio_bytes=audio, mime_type="audio/wav", duration_seconds=duration, timestamps=[])
