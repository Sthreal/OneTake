"""S5 单测：形态专属材质约束/物理反馈（`physical_actions`）与关键帧静态告警（`keyframe_static_guard`）。"""
from __future__ import annotations

import pytest

from onetake_api.integrations.product_scene.keyframe_static_guard import find_temporal_words, static_warning
from onetake_api.integrations.product_scene.physical_actions import (
    SHAPE_MATERIAL_CONSTRAINTS,
    SHAPE_PHYSICAL_ACTIONS,
    resolve_shape_from_prompt,
)
from onetake_api.modules.content_plan.product_shapes import PRODUCT_SHAPES


def test_every_shape_has_both_maps() -> None:
    assert set(SHAPE_MATERIAL_CONSTRAINTS) == set(PRODUCT_SHAPES)
    assert set(SHAPE_PHYSICAL_ACTIONS) == set(PRODUCT_SHAPES)
    assert all(text.strip() for text in SHAPE_MATERIAL_CONSTRAINTS.values())
    assert all(text.strip() for text in SHAPE_PHYSICAL_ACTIONS.values())


@pytest.mark.parametrize("shape", sorted(PRODUCT_SHAPES))
def test_reverse_lookup_cannot_drift_from_the_generator(shape: str) -> None:
    """把生成侧写的 `visual_hint` 原样塞回来，必须还原成同一个形态键。"""
    prompt = f"展示商品。（商品形态：{PRODUCT_SHAPES[shape].visual_hint}）"
    assert resolve_shape_from_prompt(prompt) == shape


def test_missing_or_empty_prompt_returns_none() -> None:
    assert resolve_shape_from_prompt("没有任何标记的描述") is None
    assert resolve_shape_from_prompt("") is None
    assert resolve_shape_from_prompt(None) is None


def test_temporal_words_are_found_in_order_without_duplicates() -> None:
    assert find_temporal_words("先展示瓶身，然后逐渐拉远") == ["先", "然后", "逐渐"]
    assert find_temporal_words("瓶身特写，静置在台面上") == []
    assert find_temporal_words(None) == []


def test_static_warning_is_silent_when_nothing_to_warn() -> None:
    assert static_warning("瓶身特写，静置在台面上") is None
    warning = static_warning("先展示瓶身，然后拉远")
    assert warning is not None and "静帧只能画一个瞬间" in warning
