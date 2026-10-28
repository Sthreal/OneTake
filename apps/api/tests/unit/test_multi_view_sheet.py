"""多视角母版共享实现单测（关键帧九宫格 与 出镜人四视角 共用这一段）。

为什么单独测它：这段是**唯一实现**，两边出错都会表现为"整图生成失败"，
所以这里把机械行为（只调一次、9:16 归一化、错误类型归属、空结果）钉死。
"""
from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from onetake_api.integrations.product_scene.keyframe_integrated import KeyframeGenerationError
from onetake_api.integrations.product_scene.multi_view import (
    MultiViewGenerationError,
    build_four_view_prompt,
    generate_multi_view_sheet,
)
from onetake_api.platform.errors import DomainError


def _png(*, width: int = 400, height: int = 600, colour: tuple[int, int, int] = (200, 60, 60)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeAdapter:
    provider_name = "fake"

    def __init__(self, *, results=None, error: Exception | None = None) -> None:
        self._results = results
        self._error = error
        self.calls: list[dict] = []

    def generate(self, *, images, prompt, negative_prompt, n, seed, size):
        self.calls.append({"images": images, "prompt": prompt, "n": n, "seed": seed, "size": size})
        if self._error is not None:
            raise self._error
        return self._results


def test_calls_model_once_and_normalises_to_9_16() -> None:
    adapter = FakeAdapter(results=[_png(width=1440, height=1440)])

    payload = generate_multi_view_sheet(
        adapter=adapter, images=[(_png(), "image/png")], prompt="p", negative_prompt="n", size="1440*2560",
    )

    assert len(adapter.calls) == 1
    assert adapter.calls[0]["n"] == 1
    with Image.open(BytesIO(payload)) as image:
        assert (image.width, image.height) == (1440, 2560)


def test_empty_result_raises_the_caller_error_class() -> None:
    adapter = FakeAdapter(results=[])

    with pytest.raises(KeyframeGenerationError):
        generate_multi_view_sheet(
            adapter=adapter, images=[(_png(), "image/png")], prompt="p", negative_prompt="n", size="1440*2560",
            error_cls=KeyframeGenerationError,
        )


def test_missing_images_is_rejected_before_any_call() -> None:
    adapter = FakeAdapter(results=[_png()])

    with pytest.raises(MultiViewGenerationError):
        generate_multi_view_sheet(adapter=adapter, images=[], prompt="p", negative_prompt="n", size="1440*2560")

    assert adapter.calls == []


def test_adapter_failure_is_wrapped_into_caller_error() -> None:
    adapter = FakeAdapter(error=RuntimeError("cloud down"))

    with pytest.raises(KeyframeGenerationError, match="九宫格整图生成失败"):
        generate_multi_view_sheet(
            adapter=adapter, images=[(_png(), "image/png")], prompt="p", negative_prompt="n", size="1440*2560",
            error_cls=KeyframeGenerationError, failure_message="九宫格整图生成失败",
        )


def test_domain_error_from_adapter_passes_through_untouched() -> None:
    class AdapterError(DomainError):
        code = "ADAPTER_ERROR"
        http_status = 502

    adapter = FakeAdapter(error=AdapterError("额度不足"))

    with pytest.raises(AdapterError):
        generate_multi_view_sheet(
            adapter=adapter, images=[(_png(), "image/png")], prompt="p", negative_prompt="n", size="1440*2560",
        )


def test_four_view_prompt_carries_name_and_appearance_anchor() -> None:
    prompt = build_four_view_prompt(name="小夏", appearance="短发、米色上衣")

    assert "小夏" in prompt
    assert "短发、米色上衣" in prompt
    assert "同一个人" in prompt
    assert "2×2" in prompt


def test_four_view_prompt_without_appearance_still_references_the_photo() -> None:
    prompt = build_four_view_prompt(name="小夏", appearance="   ")

    assert "图 1" in prompt
