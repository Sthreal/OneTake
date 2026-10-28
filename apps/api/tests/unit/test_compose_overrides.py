"""S4-④a 单测：方案级合成覆盖 → 全局配置的解析（**纯函数**，不碰 ffmpeg）。"""
from __future__ import annotations

from types import SimpleNamespace

from onetake_api.integrations.media.local_composer import ComposeOverrides


def _settings(caption_style="standard", bgm_enabled=False, bgm_gain_db=-20.0):
    return SimpleNamespace(caption_style=caption_style, bgm_enabled=bgm_enabled, bgm_gain_db=bgm_gain_db)


def test_plan_without_overrides_falls_back_to_global_settings() -> None:
    request = SimpleNamespace(caption_style=None, bgm_enabled=None, bgm_gain_db=None)
    resolved = ComposeOverrides.resolve(request, _settings(caption_style="bold", bgm_enabled=True, bgm_gain_db=-12.0))
    assert (resolved.caption_style, resolved.bgm_enabled, resolved.bgm_gain_db) == ("bold", True, -12.0)


def test_plan_override_wins_over_global_settings() -> None:
    request = SimpleNamespace(caption_style="karaoke", bgm_enabled=True, bgm_gain_db=-6.0)
    resolved = ComposeOverrides.resolve(request, _settings(caption_style="bold", bgm_enabled=False, bgm_gain_db=-12.0))
    assert (resolved.caption_style, resolved.bgm_enabled, resolved.bgm_gain_db) == ("karaoke", True, -6.0)


def test_explicit_off_and_zero_are_not_swallowed() -> None:
    """`False` / `0.0` 是**明确设置**，绝不能被 falsy 逻辑当成「没设」。"""
    request = SimpleNamespace(caption_style=None, bgm_enabled=False, bgm_gain_db=0.0)
    resolved = ComposeOverrides.resolve(request, _settings(bgm_enabled=True, bgm_gain_db=-20.0))
    assert resolved.bgm_enabled is False
    assert resolved.bgm_gain_db == 0.0
