"""Phase 1 单测：关键帧提示词、像素锁定、质检、生成器（mock 与 pixel-lock 兜底）。"""
from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw

from onetake_api.config import Settings
from onetake_api.integrations.product_scene.keyframe_integrated import KeyframeGenerator
from onetake_api.integrations.product_scene.keyframe_qa import RuleKeyframeQaAdapter
from onetake_api.integrations.product_scene.pixel_lock import lock_product_pixels
from onetake_api.integrations.product_scene.product_constraints import (
    FIDELITY_RULES,
    INTEGRATED_NEGATIVE_TERMS,
    scene_prompt_is_safe,
)
from onetake_api.modules.content_plan.domain import ContentScene
from onetake_api.modules.content_plan.prompt_schema import build_keyframe_negative_prompt, build_keyframe_prompt


def _product_png(size: int = 400) -> bytes:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((40, 80, size - 40, size - 60), radius=32, fill=(196, 42, 42, 255))
    draw.rectangle((60, 120, size - 60, 150), fill=(255, 255, 255, 255))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _scene() -> ContentScene:
    return ContentScene(
        scene_id="scene_1", order=1, purpose="selling_point", script_excerpt="文案",
        start_seconds=0.0, end_seconds=5.0, shot_type="product_reveal", prompt="",
        overlay_product=True, product_position="center", background_style="clean", template_id="clean",
        subtitle_segment_ids=[1], qa_rules=[], visual_goal="product_reveal",
        subject_action="灯光渐亮", camera_move="push_in", product_mode="integrated", transition="fade",
    )


def _png(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_keyframe_prompt_carries_fidelity_constraints() -> None:
    scene = _scene()
    prompt = build_keyframe_prompt(scene)
    assert "商品" in prompt and "保真要求" in prompt
    for rule in FIDELITY_RULES:
        assert rule in prompt
    negative = build_keyframe_negative_prompt(scene)
    for term in INTEGRATED_NEGATIVE_TERMS:
        assert term in negative


def test_scene_prompt_guard_rejects_subject_terms() -> None:
    assert scene_prompt_is_safe("木质桌面与柔和光线")
    assert not scene_prompt_is_safe("桌面上放着一个玻璃杯")


def test_pixel_lock_places_product_into_scene() -> None:
    scene = _png(Image.new("RGB", (1080, 1920), (240, 238, 230)))
    locked = lock_product_pixels(scene_image=scene, product_png=_product_png())
    with Image.open(BytesIO(locked)) as image:
        assert image.size == (1080, 1920)
        center = image.convert("RGB").crop((440, 1150, 640, 1350))
        mean = tuple(sum(channel) / (center.width * center.height) for channel in zip(*list(center.getdata())))
    # 中心区域应明显偏红（商品像素进来了），而不是背景的浅灰
    assert mean[0] > mean[2] + 40


def test_rule_qa_rejects_scene_without_product() -> None:
    qa = RuleKeyframeQaAdapter()
    empty_scene = _png(Image.new("RGB", (1080, 1920), (245, 245, 245)))
    result = qa.evaluate(image_bytes=empty_scene, product_png=_product_png())
    assert result.product_present is False
    assert result.passed is False
    assert any("商品" in issue for issue in result.issues)


def test_rule_qa_accepts_composited_keyframe() -> None:
    qa = RuleKeyframeQaAdapter()
    scene = _png(Image.new("RGB", (1080, 1920), (238, 236, 228)))
    composed = lock_product_pixels(scene_image=scene, product_png=_product_png())
    result = qa.evaluate(image_bytes=composed, product_png=_product_png())
    assert result.product_present is True
    assert result.product_match >= 0.55
    assert result.passed is True


def _settings(**overrides) -> Settings:
    base = {
        "mock_providers": True,
        "keyframe_mode": "integrated",
        "keyframe_candidates": 2,
        "keyframe_pixel_lock_fallback": True,
        "keyframe_qa_provider": "rules",
        "keyframe_image_size": "1080*1920",
    }
    base.update(overrides)
    return Settings(**base)


def test_generator_mock_mode_produces_integrated_keyframe() -> None:
    generator = KeyframeGenerator(settings=_settings())
    candidates = generator.generate(scene=_scene(), product_png=_product_png(), n=2)
    assert len(candidates) == 1  # mock 只渲染一张确定性结果
    candidate = candidates[0]
    assert candidate.mode == "integrated"
    assert (candidate.width, candidate.height) == (1080, 1920)
    assert candidate.qa.passed is True
    assert candidate.fallback is None


def test_generator_falls_back_to_pixel_lock_when_qa_fails() -> None:
    class _FakeEdit:
        provider_name = "fake-edit"

        def generate(self, **_kwargs):
            # 纯白画面：商品没进画面，规则质检必然不通过
            return [_png(Image.new("RGB", (1080, 1920), (255, 255, 255)))]

    generator = KeyframeGenerator(
        settings=_settings(mock_providers=False, dashscope_api_key="test-key"),
        image_edit=_FakeEdit(),
    )
    candidates = generator.generate(scene=_scene(), product_png=_product_png(), n=1)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.fallback == "pixel_lock"
    assert candidate.qa.passed is True


def test_generator_keeps_failure_when_fallback_disabled() -> None:
    class _FakeEdit:
        provider_name = "fake-edit"

        def generate(self, **_kwargs):
            return [_png(Image.new("RGB", (1080, 1920), (255, 255, 255)))]

    generator = KeyframeGenerator(
        settings=_settings(mock_providers=False, dashscope_api_key="test-key", keyframe_pixel_lock_fallback=False),
        image_edit=_FakeEdit(),
    )
    candidate = generator.generate(scene=_scene(), product_png=_product_png(), n=1)[0]
    assert candidate.fallback is None
    assert candidate.qa.passed is False
    assert candidate.issues
class _RecordingEdit:
    """记下**到底喂了几张图、提示词怎么写的**（人物×商品这条路唯一能被单测钉住的地方）。"""

    provider_name = "recording-edit"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return [_png(Image.new("RGB", (1080, 1920), (250, 250, 250)))]


def test_generator_feeds_character_sheet_as_second_image_with_interaction_prompt() -> None:
    """2026-10-16：出镜人母版必须**作为输入图**喂进去，并在提示词里要求"这个人手持这个商品"。

    改之前只喂商品 → 首帧必然没有人 → 整片只能是"商品在台上"（用户实测："为什么别人的人物可以和商品交互"）。
    """
    recorder = _RecordingEdit()
    generator = KeyframeGenerator(
        settings=_settings(mock_providers=False, dashscope_api_key="test-key", keyframe_pixel_lock_fallback=False),
        image_edit=recorder,
    )
    character = _product_png(size=200)  # 用任意 PNG 代表人物母版（只验"有没有传、编号对不对"）
    generator.generate(scene=_scene(), product_png=_product_png(), n=1, character_png=character)

    assert recorder.calls, "应当调用了一次图像模型"
    call = recorder.calls[-1]
    assert len(call["images"]) == 2, "商品 + 人物 = 2 张输入图"
    assert "图 2" in call["prompt"] and "手持" in call["prompt"]
    assert "第二个人" in call["negative_prompt"]


def test_generator_without_character_keeps_single_image_and_old_prompt() -> None:
    recorder = _RecordingEdit()
    generator = KeyframeGenerator(
        settings=_settings(mock_providers=False, dashscope_api_key="test-key", keyframe_pixel_lock_fallback=False),
        image_edit=recorder,
    )
    generator.generate(scene=_scene(), product_png=_product_png(), n=1)
    call = recorder.calls[-1]
    assert len(call["images"]) == 1
    assert "手持" not in call["prompt"]
    assert "第二个人" not in call["negative_prompt"]


def test_grid_image_with_character_gets_three_inputs_when_scene_reference_present() -> None:
    """上一镜参考图 + 商品 + 人物 = 3 张（qwen-image-edit 上限 3），编号必须是 图3=人物。"""
    recorder = _RecordingEdit()
    generator = KeyframeGenerator(
        settings=_settings(mock_providers=False, dashscope_api_key="test-key"),
        image_edit=recorder,
    )
    generator.generate_grid_image(
        scenes=[_scene()], product_png=_product_png(), scene_reference=_product_png(),
        character_png=_product_png(size=200),
    )
    call = recorder.calls[-1]
    assert len(call["images"]) == 3
    assert "图 3" in call["prompt"] and "手持" in call["prompt"]