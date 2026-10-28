"""视频音轨策略单测（B 项）：默认丢弃模型原声、可选保留，且"关语音=无音轨"契约不被破坏。"""
from __future__ import annotations

import wave
from io import BytesIO

from PIL import Image

from onetake_api.config import Settings
from onetake_api.integrations.media.local_composer import LocalCompositionAdapter
from onetake_api.integrations.media.video_utils import (
    concatenate_videos,
    inspect_has_audio,
    inspect_video_dimensions,
)
from onetake_api.integrations.mock_video.renderer import render_base_video
from onetake_api.modules.composition.port import CompositionRequest

WIDTH, HEIGHT, FPS = 1080, 1920, 30


def _silent_wav(seconds: float = 3.0) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(48000)
        handle.writeframes(b"\x00\x00" * int(48000 * seconds))
    return buffer.getvalue()


def _clip(*, with_audio: bool, seconds: float = 2.0) -> bytes:
    image = Image.new("RGB", (WIDTH, HEIGHT), (180, 185, 190))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    base = render_base_video(
        image_bytes=buffer.getvalue(), mode="product", template_id="clean",
        duration_seconds=seconds, width=WIDTH, height=HEIGHT, fps=FPS,
    )
    if not with_audio:
        return base
    return LocalCompositionAdapter(
        settings=Settings(mock_providers=False, composition_provider="local", video_keep_model_audio=False)
    ).compose(CompositionRequest(
        base_video_bytes=base, audio_bytes=_silent_wav(seconds), srt_bytes=None,
        duration_seconds=seconds, width=WIDTH, height=HEIGHT, fps=FPS,
    ))


def test_default_concat_strips_audio() -> None:
    """默认（keep_audio=False）：即便片段带音轨，拼接结果也必须无音轨 —— TTS 是唯一语音来源。"""
    clips = [_clip(with_audio=True), _clip(with_audio=False)]
    out = concatenate_videos(clips=clips, duration_seconds=4.0, fps=FPS)
    assert inspect_has_audio(out) is False
    assert inspect_video_dimensions(out) == (WIDTH, HEIGHT)


def test_keep_audio_concat_preserves_and_pads_silence() -> None:
    """keep_audio=True：带音轨的保留、无音轨的自动补静音，避免 concat 流不一致。"""
    clips = [_clip(with_audio=True), _clip(with_audio=False)]
    out = concatenate_videos(clips=clips, duration_seconds=4.0, fps=FPS, keep_audio=True)
    assert inspect_has_audio(out) is True


def test_composer_mixes_tts_by_default() -> None:
    composer = LocalCompositionAdapter(settings=Settings(
        mock_providers=False, composition_provider="local", video_keep_model_audio=False,
    ))
    out = composer.compose(CompositionRequest(
        base_video_bytes=_clip(with_audio=False), audio_bytes=_silent_wav(3.0), srt_bytes=None,
        duration_seconds=3.0,
        width=WIDTH, height=HEIGHT, fps=FPS,
    ))
    assert inspect_has_audio(out) is True


def test_composer_without_voice_produces_silent_track_when_keep_model_audio_off() -> None:
    """关语音 + 不保留模型原声 → 成片必须**没有**音轨（PRD 契约）。"""
    composer = LocalCompositionAdapter(settings=Settings(
        mock_providers=False, composition_provider="local", video_keep_model_audio=False,
    ))
    out = composer.compose(CompositionRequest(
        base_video_bytes=_clip(with_audio=True), audio_bytes=None, srt_bytes=None,
        duration_seconds=2.0,
        width=WIDTH, height=HEIGHT, fps=FPS,
    ))
    assert inspect_has_audio(out) is False


def test_composer_keeps_base_audio_when_keep_model_audio_on() -> None:
    composer = LocalCompositionAdapter(settings=Settings(
        mock_providers=False, composition_provider="local", video_keep_model_audio=True,
    ))
    out = composer.compose(CompositionRequest(
        base_video_bytes=_clip(with_audio=True), audio_bytes=None, srt_bytes=None,
        duration_seconds=2.0,
        width=WIDTH, height=HEIGHT, fps=FPS,
    ))
    assert inspect_has_audio(out) is True