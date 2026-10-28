"""批次 4b 单测：BGM（来源解析 + 闪避混音）。

真混音用 ffmpeg 合成音源（不联网、不花钱）：
- 旁白：2 秒 1kHz 正弦 + 1 秒静音（"静音尾巴"用来证明音乐真的进了混音）
- 音乐：1 秒 220Hz 正弦（短于成片 → 顺带覆盖 `-stream_loop` 循环）
"""
from __future__ import annotations

import hashlib
import math
import re
import struct
import subprocess
import tempfile
import wave
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from imageio_ffmpeg import get_ffmpeg_exe

from onetake_api.config import Settings
from onetake_api.integrations.media import bgm as bgm_module
from onetake_api.integrations.media.bgm import (
    BgmError,
    BgmMixSettings,
    build_ducked_mix_filter,
    resolve_bgm_track,
)
from onetake_api.integrations.media.local_composer import LocalCompositionAdapter
from onetake_api.integrations.mock_video.renderer import render_base_video
from onetake_api.modules.composition.port import CompositionRequest

WIDTH, HEIGHT, FPS, DURATION = 1080, 1920, 30, 3.0


def _settings(**overrides) -> Settings:
    base = {
        "mock_providers": False,
        "composition_provider": "local",
        "native_feel_enabled": False,
        "aigc_label_enabled": False,
    }
    base.update(overrides)
    return Settings(**base)


def _tone_wav(*, seconds: float, frequency: float, amplitude: float = 0.6, sample_rate: int = 48000) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        frames = bytearray()
        for index in range(int(sample_rate * seconds)):
            value = int(amplitude * 32767 * math.sin(2 * math.pi * frequency * index / sample_rate))
            frames += struct.pack("<h", value)
        handle.writeframes(bytes(frames))
    return buffer.getvalue()


def _voice_with_silent_tail() -> bytes:
    """2 秒有声 + 1 秒数字静音（静音尾巴是"音乐是否真的混进来"的探针）。"""
    voice = _tone_wav(seconds=2.0, frequency=1000.0)
    silence = b"\x00\x00" * 48000
    buffer = BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(48000)
        source = wave.open(BytesIO(voice), "rb")
        handle.writeframes(source.readframes(source.getnframes()) + silence)
    return buffer.getvalue()


def _silence_wav(*, seconds: float, sample_rate: int = 48000) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00" * int(sample_rate * seconds))
    return buffer.getvalue()


def _base_video() -> bytes:
    image = Image.new("RGB", (WIDTH, HEIGHT), (200, 205, 210))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return render_base_video(
        image_bytes=buffer.getvalue(), mode="product", template_id="clean",
        duration_seconds=DURATION, width=WIDTH, height=HEIGHT, fps=FPS,
    )


def _request(*, audio: bytes | None) -> CompositionRequest:
    return CompositionRequest(
        base_video_bytes=_base_video(), audio_bytes=audio, srt_bytes=None,
        duration_seconds=DURATION, width=WIDTH, height=HEIGHT, fps=FPS,
    )


def _band_volume_db(video_bytes: bytes, *, frequency: float, start: float, end: float) -> float:
    """某时间窗 + 某个频段的平均音量（用来量"闪避压了多少"：音乐是 220Hz，旁白是 1kHz）。"""
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "in.mp4"
        path.write_bytes(video_bytes)
        result = subprocess.run(
            [get_ffmpeg_exe(), "-hide_banner", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}",
             "-i", str(path), "-vn", "-af", f"bandpass=f={frequency}:width_type=h:w=60,volumedetect",
             "-f", "null", "-"],
            capture_output=True, text=True,
        )
    match = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", result.stderr)
    return float(match.group(1)) if match else float("-inf")


def _mean_volume_db(video_bytes: bytes, *, start: float, end: float) -> float:
    """某时间窗内的平均音量（dBFS）；没有音轨时返回 -inf。"""
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "in.mp4"
        path.write_bytes(video_bytes)
        result = subprocess.run(
            [get_ffmpeg_exe(), "-hide_banner", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}",
             "-i", str(path), "-vn", "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True,
        )
    match = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", result.stderr)
    return float(match.group(1)) if match else float("-inf")


# ---- 来源解析 ----


def test_resolve_bgm_track_uses_configured_path(tmp_path: Path) -> None:
    track_file = tmp_path / "my-track.wav"
    track_file.write_bytes(_tone_wav(seconds=1.0, frequency=220.0))
    track = resolve_bgm_track(settings=_settings(bgm_enabled=True, bgm_track_path=str(track_file)))
    assert track is not None
    assert track.source == "local-path" and track.name == "my-track.wav" and track.suffix == ".wav"
    assert hashlib.sha256(track.content).hexdigest() == hashlib.sha256(track_file.read_bytes()).hexdigest()


def test_resolve_bgm_track_fails_loud_when_path_missing(tmp_path: Path) -> None:
    """配了不存在的音轨必须报错：静默跳过会让用户以为叠上了。"""
    with pytest.raises(BgmError) as error:
        resolve_bgm_track(settings=_settings(bgm_enabled=True, bgm_track_path=str(tmp_path / "nope.mp3")))
    assert "不存在" in str(error.value)


def test_resolve_bgm_track_falls_back_to_bundled_library(tmp_path: Path, monkeypatch) -> None:
    library = tmp_path / "bgm"
    library.mkdir()
    (library / "a.wav").write_bytes(_tone_wav(seconds=0.5, frequency=220.0))
    (library / "b.wav").write_bytes(_tone_wav(seconds=0.5, frequency=330.0))
    monkeypatch.setattr(bgm_module, "BGM_ASSET_DIR", library)
    first = resolve_bgm_track(settings=_settings(bgm_enabled=True))
    second = resolve_bgm_track(settings=_settings(bgm_enabled=True), seed=1)
    assert first is not None and second is not None
    assert {first.name, second.name} == {"a.wav", "b.wav"}          # 稳定取模：不同 seed 可不同
    assert resolve_bgm_track(settings=_settings(bgm_enabled=True), seed=1).name == second.name
    assert first.source == "bundled" and first.attribution == "a"


def test_resolve_bgm_track_returns_none_without_any_source(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(bgm_module, "BGM_ASSET_DIR", tmp_path / "missing")
    assert resolve_bgm_track(settings=_settings(bgm_enabled=True)) is None


def test_builtin_library_is_empty_for_now() -> None:
    """内置库当前为空（免 Key 音源还没入库）—— 这条断言把"现状"钉住，避免我误以为已内置。"""
    assert bgm_module.available_bundled_tracks() == []


# ---- 滤镜图（纯函数）----


def test_build_ducked_mix_filter_shape() -> None:
    graph = build_ducked_mix_filter(
        voice_index=1, bgm_index=2, duration_seconds=18.0, gain_db=-20.0, threshold=0.03, ratio=12.0,
    )
    assert "[1:a]loudnorm=I=-14:TP=-1.5:LRA=11,alimiter=limit=0.95:level=false,aformat=sample_rates=48000:channel_layouts=stereo,asplit=2[voice][sc]" in graph
    assert "[2:a]atrim=0:18.000,volume=-20.0dB,aformat=sample_rates=48000:channel_layouts=stereo[bgm]" in graph
    assert "[bgm][sc]sidechaincompress=threshold=0.03:ratio=12.0:attack=20:release=350[bgmduck]" in graph
    assert graph.endswith("[voice][bgmduck]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95:level=false[a]")


# ---- 真混音 ----


def test_bgm_mix_puts_music_in_silent_gaps_without_swamping_voice(tmp_path: Path) -> None:
    bgm_file = tmp_path / "bgm.wav"
    bgm_file.write_bytes(_tone_wav(seconds=1.0, frequency=220.0))
    voice = _voice_with_silent_tail()
    with_bgm = LocalCompositionAdapter(
        settings=_settings(bgm_enabled=True, bgm_track_path=str(bgm_file))
    ).compose(_request(audio=voice))
    without_bgm = LocalCompositionAdapter(settings=_settings(bgm_enabled=False)).compose(_request(audio=voice))

    # 静音尾巴（2.3~2.9s）：开 BGM 有音乐、关 BGM 是静音
    tail_with = _mean_volume_db(with_bgm, start=2.3, end=2.9)
    tail_without = _mean_volume_db(without_bgm, start=2.3, end=2.9)
    assert tail_with > -60, tail_with
    assert tail_without < -60, tail_without
    # 旁白段（0.3~1.6s）：叠 BGM 后旁白不该被压下去（差 ≤ 4dB）
    voice_with = _mean_volume_db(with_bgm, start=0.3, end=1.6)
    voice_without = _mean_volume_db(without_bgm, start=0.3, end=1.6)
    assert abs(voice_with - voice_without) <= 4.0, (voice_with, voice_without)


def test_ducking_reduces_music_under_the_voice(tmp_path: Path) -> None:
    """闪避的可测证据：同一时间窗内，音乐频段（220Hz）在"有旁白"时比"无旁白"时低 ≥6dB。"""
    bgm_file = tmp_path / "bgm.wav"
    bgm_file.write_bytes(_tone_wav(seconds=1.0, frequency=220.0))
    adapter = LocalCompositionAdapter(settings=_settings(bgm_enabled=True, bgm_track_path=str(bgm_file)))
    with_voice = adapter.compose(_request(audio=_voice_with_silent_tail()))
    with_silence = adapter.compose(_request(audio=_silence_wav(seconds=3.0)))     # 纯静音"旁白" → 不触发闪避
    ducked = _band_volume_db(with_voice, frequency=220.0, start=0.4, end=1.6)
    unducked = _band_volume_db(with_silence, frequency=220.0, start=0.4, end=1.6)
    assert unducked - ducked >= 6.0, (unducked, ducked)


def test_bgm_is_skipped_without_voice_track(tmp_path: Path) -> None:
    """既有契约：没有旁白轨就不该有音轨 —— 开了 BGM 也不能例外。"""
    bgm_file = tmp_path / "bgm.wav"
    bgm_file.write_bytes(_tone_wav(seconds=1.0, frequency=220.0))
    output = LocalCompositionAdapter(
        settings=_settings(bgm_enabled=True, bgm_track_path=str(bgm_file))
    ).compose(_request(audio=None))
    assert _mean_volume_db(output, start=0.0, end=2.9) == float("-inf")


def test_bgm_disabled_output_matches_legacy(tmp_path: Path) -> None:
    """关掉开关就完全不走 BGM 分支（即使配了音轨）：成片与改造前逐字节一致。"""
    bgm_file = tmp_path / "bgm.wav"
    bgm_file.write_bytes(_tone_wav(seconds=1.0, frequency=220.0))
    voice = _voice_with_silent_tail()
    legacy = LocalCompositionAdapter(settings=_settings()).compose(_request(audio=voice))
    configured_but_off = LocalCompositionAdapter(
        settings=_settings(bgm_enabled=False, bgm_track_path=str(bgm_file))
    ).compose(_request(audio=voice))
    assert hashlib.sha256(configured_but_off).hexdigest() == hashlib.sha256(legacy).hexdigest()


def test_bgm_mix_settings_from_settings_reads_knobs() -> None:
    mix = BgmMixSettings.from_settings(_settings(bgm_gain_db=-18.5, bgm_duck_threshold=0.05, bgm_duck_ratio=8.0))
    assert (mix.gain_db, mix.duck_threshold, mix.duck_ratio) == (-18.5, 0.05, 8.0)