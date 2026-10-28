"""Phase 4 单测：本地合成的纯函数部分 + 端到端 FFmpeg 合成（顺序与产物校验）。"""
from __future__ import annotations

import wave
from io import BytesIO

import pytest
from PIL import Image

from onetake_api.config import Settings
from onetake_api.integrations.media import aigc_label as aigc_label_module
from onetake_api.integrations.media.aigc_label import draw_aigc_label, resolve_position
from onetake_api.integrations.media.aigc_label_png import (
    build_label_overlay_png,
    resolve_font_size,
    resolve_margin,
)
from onetake_api.integrations.media.local_composer import LocalCompositionAdapter, LocalComposerError
from onetake_api.integrations.media.native_feel import apply_native_feel, build_filter_chain
from onetake_api.integrations.media.video_utils import inspect_video_dimensions, inspect_video_duration
from onetake_api.integrations.mock_video.renderer import render_base_video
from onetake_api.modules.composition.port import CompositionRequest

WIDTH, HEIGHT, FPS = 1080, 1920, 30


def _base_video(duration: float = 3.0) -> bytes:
    image = Image.new("RGB", (WIDTH, HEIGHT), (200, 205, 210))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return render_base_video(
        image_bytes=buffer.getvalue(), mode="product", template_id="clean",
        duration_seconds=duration, width=WIDTH, height=HEIGHT, fps=FPS,
    )


def _silent_wav(duration: float = 3.0) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(48000)
        handle.writeframes(b"\x00\x00" * int(48000 * duration))
    return buffer.getvalue()


def _settings(**overrides) -> Settings:
    base = {
        "mock_providers": False,
        "composition_provider": "local",
        "native_feel_enabled": False,
        "aigc_label_enabled": False,
    }
    base.update(overrides)
    return Settings(**base)


def _request(*, audio: bytes | None = None, srt: bytes | None = None) -> CompositionRequest:
    """合成请求：M4-03 提交 4 之后**不再有**任何"叠商品"参数。"""
    return CompositionRequest(
        base_video_bytes=_base_video(), audio_bytes=audio, srt_bytes=srt,
        duration_seconds=3.0, width=WIDTH, height=HEIGHT, fps=FPS,
    )


# ---- 纯函数部分 ----


def test_native_feel_filter_chain_is_deterministic_and_keeps_frame_size() -> None:
    first = build_filter_chain(width=WIDTH, height=HEIGHT, strength="subtle", seed=7)
    second = build_filter_chain(width=WIDTH, height=HEIGHT, strength="subtle", seed=7)
    other = build_filter_chain(width=WIDTH, height=HEIGHT, strength="subtle", seed=8)
    assert first == second          # 同 seed 可复现
    assert first != other           # 不同 seed → A/B 变体
    # margin = 幅度*2 + 2 = 10 → crop 1070x1910 后再放大回 1080x1920\n    assert "crop=1070:1910" in first
    assert first.endswith("[v]")
    assert "noise=" in first


def test_native_feel_strength_changes_amplitude() -> None:
    subtle = build_filter_chain(width=WIDTH, height=HEIGHT, strength="subtle")
    strong = build_filter_chain(width=WIDTH, height=HEIGHT, strength="strong")
    assert "4.0*sin" in subtle
    assert "13.0*sin" in strong


def test_native_feel_halation_uses_split_blend() -> None:
    chain = build_filter_chain(width=WIDTH, height=HEIGHT, halation=True)
    assert "split=2" in chain and "blend=all_mode=screen" in chain


def test_aigc_label_position_and_size_contract() -> None:
    """S6 改造后：断言从「滤镜字符串」升级为「像素落点」——验的是字真的画上去了。"""
    # 位置避让逻辑不变（compliance/labels.py 也依赖 resolve_position）
    assert resolve_position(position="bottom_right", avoid_subtitle=True) == "top_right"
    assert resolve_position(position="bottom_left", avoid_subtitle=True) == "top_left"
    assert resolve_position(position="bottom_right", avoid_subtitle=False) == "bottom_right"
    # 字号与边距仍按帧宽比例（1080 × 0.028 ≈ 30 ／ 1080 × 0.04 ≈ 43）
    assert resolve_font_size(WIDTH, 0.028) == 30
    assert resolve_margin(WIDTH, 0.04) == 43
    # 位图叠加：全帧 RGBA，文字落在右上角，且外沿与 drawtext 的 margin 口径一致
    overlay = build_label_overlay_png(text="AI生成", width=WIDTH, height=HEIGHT, position="top_right")
    with Image.open(BytesIO(overlay)) as image:
        assert image.size == (WIDTH, HEIGHT)
        assert image.mode == "RGBA"
        box = image.convert("RGBA").getchannel("A").getbbox()
    assert box is not None, "标识未画出任何可见像素"
    x0, y0, x1, y1 = box
    assert x0 > WIDTH // 2 and y1 < HEIGHT // 2
    assert abs(y0 - (43 - 2)) <= 1                       # 上沿贴 margin，2px 描边外溢
    assert abs(x1 - (WIDTH - 43)) <= 2                   # 右沿贴 margin，2px 描边外溢


def test_draw_aigc_label_call_uses_overlay_not_drawtext(monkeypatch) -> None:
    """S6 验收（比手写 grep 更强）：真实 ffmpeg 调用里必须是 overlay、不得出现 drawtext。

    容器镜像的 imageio-ffmpeg 缺 freetype → drawtext 滤镜不存在；这条断言把
    「不许再用 drawtext」变成每次 pytest 都会执行的行为约束，而不是一次性人工检查。
    """
    import subprocess as subprocess_module
    from pathlib import Path as PathClass

    captured: dict[str, list[str]] = {}

    def fake_run(command, **kwargs):  # noqa: ANN001, ANN003
        captured["command"] = list(command)
        PathClass(command[-1]).write_bytes(b"ftypstub")
        return subprocess_module.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(aigc_label_module.subprocess, "run", fake_run)
    aigc_label_module.draw_aigc_label(_base_video(1.0), width=WIDTH, height=HEIGHT)

    joined = " ".join(captured["command"])
    assert "drawtext" not in joined
    assert "overlay=0:0" in joined


def test_aigc_label_requires_text_and_input() -> None:
    with pytest.raises(Exception):
        draw_aigc_label(b"", width=WIDTH, height=HEIGHT)
    with pytest.raises(Exception):
        draw_aigc_label(_base_video(1.0), width=WIDTH, height=HEIGHT, text="   ")


def test_local_composer_rejects_empty_input() -> None:
    adapter = LocalCompositionAdapter(settings=_settings())
    with pytest.raises(LocalComposerError):
        adapter.compose(CompositionRequest(
            base_video_bytes=b"", audio_bytes=None, srt_bytes=None,
            duration_seconds=3.0, width=WIDTH, height=HEIGHT, fps=FPS,
        ))


# ---- 端到端（真实 FFmpeg）----


def test_native_feel_keeps_dimensions_and_audio() -> None:
    output = apply_native_feel(_base_video(2.0), width=WIDTH, height=HEIGHT, fps=FPS, strength="medium", seed=3)
    assert inspect_video_dimensions(output) == (WIDTH, HEIGHT)
    assert abs(inspect_video_duration(output) - 2.0) < 0.4


def test_composer_mixes_audio_and_burns_subtitles() -> None:
    adapter = LocalCompositionAdapter(settings=_settings())
    srt = "1\n00:00:00,000 --> 00:00:02,000\n测试字幕\n".encode("utf-8")
    output = adapter.compose(_request(audio=_silent_wav(), srt=srt))
    assert inspect_video_dimensions(output) == (WIDTH, HEIGHT)
    assert abs(inspect_video_duration(output) - 3.0) < 0.5


def test_composer_draws_aigc_label_last() -> None:
    """标识必须在最后一步：直接比对「开/关标识」两次合成在右上角区域的像素差异。"""
    without = LocalCompositionAdapter(settings=_settings()).compose(_request(audio=_silent_wav()))
    with_label = LocalCompositionAdapter(
        settings=_settings(aigc_label_enabled=True, aigc_label_source="local")
    ).compose(_request(audio=_silent_wav()))
    assert inspect_video_dimensions(with_label) == (WIDTH, HEIGHT)
    changed = _region_diff_ratio(without, with_label, seconds=1.0, box=(WIDTH - 320, 0, WIDTH, 160))
    # 右上角应当出现明显像素改动（文字与描边）
    assert changed > 0.002


def test_composer_skips_label_when_disabled() -> None:
    without = LocalCompositionAdapter(settings=_settings()).compose(_request(audio=_silent_wav()))
    other = LocalCompositionAdapter(settings=_settings(aigc_label_enabled=False)).compose(_request(audio=_silent_wav()))
    changed = _region_diff_ratio(without, other, seconds=1.0, box=(WIDTH - 320, 0, WIDTH, 160))
    assert changed < 0.002


def test_composer_runs_native_feel_when_enabled() -> None:
    output = LocalCompositionAdapter(
        settings=_settings(native_feel_enabled=True, native_feel_strength="subtle")
    ).compose(_request(audio=_silent_wav()))
    assert inspect_video_dimensions(output) == (WIDTH, HEIGHT)
    assert abs(inspect_video_duration(output) - 3.0) < 0.5


def _region_diff_ratio(
    first_video: bytes, second_video: bytes, *, seconds: float, box: tuple[int, int, int, int]
) -> float:
    """两个视频在同一时刻、同一区域的"明显不同像素"占比（用于证明某步骤真的生效）。"""
    import subprocess
    import tempfile
    from pathlib import Path

    from imageio_ffmpeg import get_ffmpeg_exe

    def _frame(video_bytes: bytes) -> Image.Image:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video_path = root / "input.mp4"
            frame_path = root / "frame.png"
            video_path.write_bytes(video_bytes)
            subprocess.run(
                [get_ffmpeg_exe(), "-y", "-ss", f"{seconds:.3f}", "-i", str(video_path),
                 "-frames:v", "1", str(frame_path)],
                check=True, capture_output=True, text=True,
            )
            with Image.open(frame_path) as image:
                return image.convert("RGB").crop(box).copy()

    left = _frame(first_video).getdata()
    right = _frame(second_video).getdata()
    total = 0
    changed = 0
    for (lr, lg, lb), (rr, rg, rb) in zip(left, right):
        total += 1
        if max(abs(lr - rr), abs(lg - rg), abs(lb - rb)) > 24:
            changed += 1
    return changed / max(1, total)

def test_composition_provider_selects_local_when_configured(monkeypatch) -> None:
    """COMPOSITION_PROVIDER=local 时必须真的走本地 FFmpeg，而不是 Shotstack。"""
    from onetake_api.config import get_settings
    from onetake_api.modules.composition.service import get_composition_provider

    monkeypatch.setenv("MOCK_PROVIDERS", "false")
    monkeypatch.setenv("COMPOSITION_PROVIDER", "local")
    get_settings.cache_clear()
    try:
        provider = get_composition_provider()
        assert isinstance(provider, LocalCompositionAdapter)
        assert provider.provider_name == "local-ffmpeg"
    finally:
        get_settings.cache_clear()


def test_composition_provider_prefers_mock_when_mock_enabled(monkeypatch) -> None:
    """MOCK_PROVIDERS=true 时任何配置都不得触发真实合成（安全锁）。"""
    from onetake_api.config import get_settings
    from onetake_api.integrations.mock_video.composition import MockCompositionAdapter
    from onetake_api.modules.composition.service import get_composition_provider

    monkeypatch.setenv("MOCK_PROVIDERS", "true")
    monkeypatch.setenv("COMPOSITION_PROVIDER", "local")
    get_settings.cache_clear()
    try:
        assert isinstance(get_composition_provider(), MockCompositionAdapter)
    finally:
        get_settings.cache_clear()

def test_composition_request_no_longer_carries_product_overlay_fields() -> None:
    """M4-03 提交 4：合成契约**不再能叠商品** —— 字段是被真正删掉，而不是留成恒 false。

    保留恒 false 的字段会留下"以为还能叠商品"的误导（方案 §七）。
    """
    import dataclasses

    names = {field.name for field in dataclasses.fields(CompositionRequest)}
    assert "overlay_product" not in names
    assert "product_image_bytes" not in names
    assert "product_layers" not in names

def test_local_composer_passes_caption_style_and_frame_width(monkeypatch) -> None:
    """批次 1a：样式与帧宽必须真的透传到 burn_subtitles（否则"选了样式没生效"）。"""
    captured: dict[str, object] = {}

    def fake_burn(**kwargs):
        captured.update(kwargs)
        return b"captioned"

    monkeypatch.setattr("onetake_api.integrations.media.local_composer.burn_subtitles", fake_burn)
    srt = "1\n00:00:00,000 --> 00:00:02,000\n测试字幕\n".encode("utf-8")
    output = LocalCompositionAdapter(settings=_settings(caption_style="bold")).compose(
        _request(audio=_silent_wav(), srt=srt)
    )
    assert output == b"captioned"
    assert captured["width"] == WIDTH
    assert captured["style"] == "bold"