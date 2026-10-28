"""S14 / M4-02 单测：商品段运镜滤镜（纯字符串生成，不调 ffmpeg）。

对应档案 M4-02 第五节验收标准的 2 / 2.1 / 3 / 3.1 / 4.1 / 7。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from onetake_api.integrations.mock_video import motion_filters
from onetake_api.integrations.mock_video.motion_filters import (
    DEFAULT_MOTION,
    MOTIONS,
    PAN_RATE,
    ZOOM_MAX_SCALE,
    build_motion_filter,
)

CANVAS_W, CANVAS_H = 720, 1280  # 2× of 360×640（与 renderer 传入的画布一致）


def _f(motion: str, *, width: int = CANVAS_W, height: int = CANVAS_H, fps: int = 30, seconds: float = 5.0) -> str:
    return build_motion_filter(motion, width=width, height=height, fps=fps, duration_seconds=seconds)


def _number(pattern: str, text: str) -> float:
    match = re.search(pattern, text)
    assert match is not None, f"未能从 {text!r} 中解析出 {pattern!r}"
    return float(match.group(1))


def test_motion_list_is_the_six_agreed_keys() -> None:
    assert MOTIONS == ("zoom_in_slow", "zoom_out_slow", "pan_left", "pan_right", "ken_burns", "static")
    assert DEFAULT_MOTION == "zoom_in_slow"


@pytest.mark.parametrize("motion", MOTIONS)
def test_every_motion_emits_zoompan_on_the_given_canvas(motion: str) -> None:
    """验收 2：六种运镜都生成 zoompan（含 static），且画布尺寸 == 传入值（模块不自放大）。"""
    chain = _f(motion)
    assert chain.startswith("zoompan=")
    assert f"s={CANVAS_W}x{CANVAS_H}" in chain
    assert re.search(r"fps=30(?::|$)", chain)
    # 模块不得自行放大：不得出现 2× 画布（1440×2560）
    assert "1440" not in chain and "2560" not in chain


@pytest.mark.parametrize("motion", MOTIONS)
def test_filter_shape_is_uniform_across_motions(motion: str) -> None:
    """验收 2：滤镜图形状一致（z 必有；x/y 可缺），拼接路径无需特判。"""
    assert re.fullmatch(r"zoompan=z='[^']+'(?::[xy]='[^']+'){0,2}:d=1:s=\d+x\d+:fps=\d+", _f(motion))


@pytest.mark.parametrize("motion", ("zoom_in_slow", "zoom_out_slow", "static"))
def test_pure_zoom_motions_omit_xy(motion: str) -> None:
    """纯缩放类沿用 zoompan 的居中默认（不写 x/y）——这是与改造前等价的关键。"""
    assert ":x=" not in _f(motion) and ":y=" not in _f(motion)


@pytest.mark.parametrize("motion", ("pan_left", "pan_right", "ken_burns"))
def test_translation_motions_declare_xy(motion: str) -> None:
    chain = _f(motion)
    assert ":x='" in chain and ":y='" in chain


def test_pan_displacement_is_proportional_to_canvas_width() -> None:
    """验收 3：分辨率无关 —— 系数是常量，随宽度缩放由 `iw` 完成；宽度翻倍则每帧位移翻倍。"""
    narrow, wide = _f("pan_right", width=720), _f("pan_right", width=1440)
    k_narrow = _number(r"iw\*([0-9.]+)", narrow)
    k_wide = _number(r"iw\*([0-9.]+)", wide)
    assert k_narrow == k_wide == PAN_RATE, "系数必须与画布无关（否则不是分辨率无关）"
    assert 1440 * k_wide == pytest.approx(2 * (720 * k_narrow)), "宽度翻倍 → 每帧位移必须翻倍"


def test_motion_module_does_not_decide_supersampling() -> None:
    """验收 3.1：超采样解耦 —— 画布策略只允许出现在 renderer.py。"""
    source = Path(motion_filters.__file__).read_text(encoding="utf-8")
    assert "ZOOM_SUPERSAMPLE" not in source


def test_unknown_motion_falls_back_to_default_without_raising() -> None:
    """验收 4.1：非法键回退 DEFAULT_MOTION，不抛错、不返回空串。"""
    for bad in ("不存在的运镜", "", "pan_up", "ZOOM_IN_SLOW", "none"):
        chain = _f(bad)
        assert chain == _f(DEFAULT_MOTION)
        assert chain != ""


def test_zoom_in_is_linear_with_the_pre_change_formula() -> None:
    """验收 7：保持线性、且与改造前逐字相同的算式（0.05/150 帧 = 0.00033333）。"""
    chain = _f("zoom_in_slow")
    assert f"zoompan=z='min(1+0.00033333*on,{ZOOM_MAX_SCALE})'" in chain
    for easing in ("ease", "interpolate", "sqrt", "pow(", "^"):
        assert easing not in chain, f"不得引入缓动（{easing}）"


def test_zoom_out_mirrors_zoom_in() -> None:
    assert f"zoompan=z='max({ZOOM_MAX_SCALE}-0.00033333*on,1)'" in _f("zoom_out_slow")


def test_static_uses_zoompan_with_unit_zoom() -> None:
    """借鉴项 4：static 也用 zoompan（z='1'），保持形状一致。"""
    assert "zoompan=z='1'" in _f("static")


def test_pan_directions_are_mirrored() -> None:
    left, right = _f("pan_left"), _f("pan_right")
    assert f"x='max(iw-iw/zoom-on*(iw*{PAN_RATE}),0)'" in left, "左移：取景窗从右端向左走"
    assert f"x='min(on*(iw*{PAN_RATE}),iw-iw/zoom)'" in right, "右移：取景窗从左端向右走"


def test_pan_is_clamped_to_the_available_room() -> None:
    """平移不能越界（越界会把画面推出画布）：两条表达式都必须夹在有效行程内。"""
    for motion in ("pan_left", "pan_right", "ken_burns"):
        chain = _f(motion)
        assert "iw-iw/zoom" in chain, f"{motion} 未夹到可用行程"


def test_zoom_step_scales_inversely_with_duration() -> None:
    """线性口径：步长 = 幅度 / 总帧数 → 时长翻倍则步长减半。

    步长按 8 位小数格式化（与改造前算式一致），所以这里锁定格式化后的精确串，
    而不是用容差比较——8 位小数的舍入本身就是被锁定的行为。
    """
    assert "min(1+0.00033333*on,1.05)" in _f("zoom_in_slow", seconds=5.0)   # 0.05 / 150 帧
    assert "min(1+0.00016667*on,1.05)" in _f("zoom_in_slow", seconds=10.0)  # 0.05 / 300 帧