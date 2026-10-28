"""Phase 2 单测：首尾帧（kf2v）适配器选择与成对生成分支。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from onetake_api.config import Settings, get_settings
from onetake_api.integrations.media.video_utils import ANCHOR_SOURCE_INTEGRATED_KEYFRAME, SegmentAnchor
from onetake_api.modules.video_plan.segment_generation import (
    MockSegmentAdapter,
    SegmentVideoGenerator,
    _default_pair_adapter,
)


def _plan() -> SimpleNamespace:
    return SimpleNamespace(id="vid_1", project_id="prj_1", width=1080, height=1920, fps=30, template_id="clean")


def test_anchor_accepts_integrated_keyframe_source() -> None:
    anchor = SegmentAnchor(frame_bytes=b"png", source=ANCHOR_SOURCE_INTEGRATED_KEYFRAME, end_frame_bytes=b"end")
    assert anchor.end_frame_bytes == b"end"


def test_pair_adapter_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIDEO_KF2V_ENABLED", "false")
    get_settings.cache_clear()
    assert _default_pair_adapter(_plan()) is None
    get_settings.cache_clear()


def test_pair_adapter_returns_mock_in_mock_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIDEO_KF2V_ENABLED", "true")
    monkeypatch.setenv("MOCK_PROVIDERS", "true")
    get_settings.cache_clear()
    adapter = _default_pair_adapter(_plan())
    assert isinstance(adapter, MockSegmentAdapter)
    assert hasattr(adapter, "generate_pair")
    get_settings.cache_clear()


def test_pair_adapter_returns_none_without_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """真实模式下缺 WAN_KF2V_MODEL 时必须返回 None（回退 i2v），而不是构造一个会失败的适配器。"""
    monkeypatch.setenv("VIDEO_KF2V_ENABLED", "true")
    monkeypatch.setenv("MOCK_PROVIDERS", "false")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.setenv("WAN_KF2V_MODEL", "")
    get_settings.cache_clear()
    assert _default_pair_adapter(_plan()) is None
    get_settings.cache_clear()


class _SingleAdapter:
    provider_name = "fake-single"

    def generate(self, **_kwargs):  # pragma: no cover - 本用例只验证选择逻辑
        return b"single", "t"


class _PairAdapter(_SingleAdapter):
    provider_name = "fake-pair"

    def generate_pair(self, **_kwargs):  # pragma: no cover
        return b"pair", "t"


def test_generator_prefers_pair_adapter_when_end_frame_present() -> None:
    pair = _PairAdapter()
    single = _SingleAdapter()
    generator = SegmentVideoGenerator(
        storage=None,
        adapter_factory=lambda plan: single,
        pair_adapter_factory=lambda plan: pair,
    )
    assert generator._resolve_adapter(_plan(), pair=True) is pair
    assert generator._resolve_adapter(_plan(), pair=False) is single


def test_generator_falls_back_to_single_when_pair_unavailable() -> None:
    single = _SingleAdapter()
    generator = SegmentVideoGenerator(
        storage=None,
        adapter_factory=lambda plan: single,
        pair_adapter_factory=lambda plan: None,
    )
    # 拿不到成对适配器时退回单帧 i2v，而不是静默假装用了首尾帧
    assert generator._resolve_adapter(_plan(), pair=True) is single