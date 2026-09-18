from io import BytesIO
from types import SimpleNamespace
from wave import open as wave_open

import pytest

from onetake_api.integrations.cosyvoice.adapter import CosyVoiceV2Adapter, CosyVoiceError
from onetake_api.integrations.mock_voice.adapter import MockVoiceAdapter


def test_mock_voice_generates_wav() -> None:
    result = MockVoiceAdapter().synthesize(text="这是一个测试文案。", voice_id="female", language="zh", speed=1.0)
    assert result.mime_type == "audio/wav"
    assert result.duration_seconds >= 3
    with wave_open(BytesIO(result.audio_bytes)) as wav:
        assert wav.getnchannels() == 1
        assert wav.getframerate() == 24000


def test_cosyvoice_adapter_uses_sdk_result(monkeypatch) -> None:
    audio = MockVoiceAdapter().synthesize(text="测试", voice_id="female", language="zh", speed=1.0).audio_bytes

    class FakeResult:
        def get_audio_data(self):
            return audio

        def get_timestamps(self):
            return [{"text": "测试", "begin_time": 0, "end_time": 1000}]

    class FakeSpeechSynthesizer:
        def __init__(self, **kwargs):
            assert kwargs["model"] == "cosyvoice-v2"
            assert kwargs["voice"] == "longxiaochun_v2"

        def call(self, text, timeout_millis=None):
            return audio

    monkeypatch.setitem(__import__("sys").modules, "dashscope", SimpleNamespace(api_key=""))
    monkeypatch.setitem(__import__("sys").modules, "dashscope.audio.tts_v2", SimpleNamespace(AudioFormat=SimpleNamespace(WAV_48000HZ_MONO_16BIT="wav"), SpeechSynthesizer=FakeSpeechSynthesizer))
    adapter = CosyVoiceV2Adapter(api_key="test-key", model="cosyvoice-v2")
    result = adapter.synthesize(text="测试", voice_id="longxiaochun_v2", language="zh", speed=1.0)
    assert result.duration_seconds > 0
    assert result.timestamps == []


def test_cosyvoice_requires_key() -> None:
    adapter = CosyVoiceV2Adapter(api_key="", model="cosyvoice-v2")
    with pytest.raises(CosyVoiceError):
        adapter.synthesize(text="测试", voice_id="longxiaochun_v2", language="zh", speed=1.0)
